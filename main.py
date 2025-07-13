import wave
from logging import getLogger
from os import getenv
from typing import IO, Final

import audioop
import discord
from discord.opus import Encoder as OpusEncoder
from dotenv import load_dotenv

logger: Final = getLogger(__name__)

# 設定の読み込み
load_dotenv()

opus_lib_path = getenv("OPUS_LIB_PATH")
token = getenv("TOKEN")
if token is None:
    raise Exception("トークンを指定してください。")

# Opusの準備
if not discord.opus.is_loaded():
    if opus_lib_path is None:
        raise Exception(
            "Opusライブラリを探したところ、見つかりませんでした。"
            "環境変数`OPUS_LIB_PATH`で設定してください。"
        )

    discord.opus.load_opus(opus_lib_path)

# Botのクライアントの設定
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


# 諸々のイベントハンドラ
@client.event
async def on_ready() -> None:
    logger.info("起動しました。")


@client.event
async def on_message(message: discord.Message) -> None:
    # BotまたはDMなどの場合早期リターン。
    if (
        message.author.bot
        or message.guild is None
        or not isinstance(message.author, discord.Member)
    ):
        return

    # コマンド
    if message.content.startswith("wave!play"):
        if message.author.voice is None or message.author.voice.channel is None:
            await message.reply("音声チャンネルに接続してから実行してください。")
        else:
            await message.reply("再生します。")

            file_path = message.content.partition(" ")[-1] or None
            await play(message.author.voice.channel, file_path)

    if message.content == "wave!stop":
        await message.reply("停止します。")
        await stop(message.guild.id)


# 音声再生の実装
pool = dict[int, discord.VoiceClient]()  # key: ギルドID


async def play(
    channel: discord.VoiceChannel | discord.StageChannel,
    file_path: str | None = None,
):
    """音源を再生する。"""
    # 未接続なら接続する。
    if channel.guild.id not in pool:
        logger.info("ボイスチャンネル%dに接続。", channel.id)

        vc = await channel.connect()
        pool[channel.guild.id] = vc

    # 既に何か再生されてるなら止める。
    vc = pool[channel.guild.id]
    if vc.is_playing():
        vc.stop()

    # 再生を開始する。
    file_path = file_path or "audio/musicbox.wav"
    logger.info("`%s`の再生。", file_path)

    f = open(file_path, "rb")
    pool[channel.guild.id].play(WavAudio(f), after=lambda _: f.close())


async def stop(guild_id: int) -> None:
    """音声の再生をストップし、切断する。"""
    vc = pool.get(guild_id)
    if vc is None:
        return

    if vc.is_playing():
        vc.stop()

    logger.info("ボイスチャンネル%dから切断。", vc.channel.id)
    await vc.disconnect()
    del pool[guild_id]


# Wavファイルの再生をする、`AudioSource`の実装
class WavAudio(discord.AudioSource):
    def __init__(self, stream: IO[bytes]) -> None:
        self._wav: wave.Wave_read = wave.open(stream)

        # wavファイルの情報を取得する。

        # sampling_rate: サンプリングレート、１秒間にいくつのサンプルがあるか。
        # samples_per_frame: 20msのデータのサンプル数
        # sample_size: 一つのサンプルが何バイトか
        # frame_size: 20msが何バイトになるか

        sampling_rate = self._wav.getframerate()
        self.samples_per_frame = int(sampling_rate / 1000 * OpusEncoder.FRAME_LENGTH)
        self.sample_size = self._wav.getsampwidth() * self._wav.getnchannels()
        self.frame_size = self.samples_per_frame * self.sample_size

        # 音声の変換で使う状態
        self._is_first = True
        self._ratecv_state = None

    def read(self) -> bytes:
        # `discord.AudioSource`が20msのデータ欲しているので、20ms分のデータを読み込む。
        samples = self._wav.readframes(self.samples_per_frame)

        # `discord.AudioSource`は16ビットの48kHzのステレオ音声である必要がある。
        # そのため、それに変換を行う。
        samples = self._convert_dpy_specific(samples)

        # 音声が適切に20ms分足りるか確認する。
        if len(samples) != OpusEncoder.FRAME_SIZE:
            if self._is_first:
                # データを読み込むのが初回の場合、サンプリングレートの変換の仕様上、少しデータの最が欠ける。
                # そのため、無音データを挟む
                lack_bytes = OpusEncoder.FRAME_SIZE - len(samples)
                samples = bytes(lack_bytes) + samples

                self._is_first = False
            elif len(samples) > 0:
                # データを読み込むのが最初ではないが、データ数が20ms分に達しない場合、音声の最後。
                # そのため、無音データを後ろに挟んで20msにする。
                lack_bytes = OpusEncoder.FRAME_SIZE - len(samples)
                samples += bytes(lack_bytes)

        return samples

    def _convert_dpy_specific(self, samples: bytes) -> bytes:
        """渡されたPCM音声データを、`discord.AudioSource`の要求する形に変更する。"""
        SAMPLE_WIDTH_8BIT = 1  # 1バイト
        SAMPLE_WIDTH_16BIT = 2  # 2バイト

        # 16ビットにする。
        if self._wav.getsampwidth() != SAMPLE_WIDTH_16BIT:
            previous_width = self._wav.getsampwidth()

            # wavの8ビットは符号無しだが、16、24、そして32ビットの場合符号付き。ただ、8ビットも符号付きで扱いたい。
            # そのため、もしwavファイルが8ビットなら、0~255ではなく-128~127の範囲にする必要がある。
            if previous_width == SAMPLE_WIDTH_8BIT:
                samples = audioop.bias(samples, SAMPLE_WIDTH_8BIT, -128)

            samples = audioop.lin2lin(samples, previous_width, SAMPLE_WIDTH_16BIT)

        # 48kHzにする。
        if self._wav.getframerate() != OpusEncoder.SAMPLING_RATE:
            samples, self._ratecv_state = audioop.ratecv(
                samples,
                SAMPLE_WIDTH_16BIT,
                self._wav.getnchannels(),
                self._wav.getframerate(),
                OpusEncoder.SAMPLING_RATE,
                self._ratecv_state,
            )

        # ステレオにする。
        if self._wav.getnchannels() != OpusEncoder.CHANNELS:
            samples = audioop.tostereo(samples, SAMPLE_WIDTH_16BIT, 1.0, 1.0)

        return samples

    def cleanup(self) -> None:
        self._wav.close()


if __name__ == "__main__":
    client.run(token, root_logger=True)
