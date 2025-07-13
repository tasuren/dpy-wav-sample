# dpy-wav-sample
discord.pyでFFmpegを使わずにwavファイルを再生するコードのサンプル。

## 使い方
昔ながらのメッセージのコマンドを使うので、メッセージコンテンツインテントを有効にしてください。
`uv sync`で依存関係を用意して、`.env.template`を参考に設定ファイル`.env`を作成し、`uv run main.py`で起動できます。

### コマンド一覧
- `wave!play <waveファイルのパス>`  
    接続して指定された音声を再生します。音声が未指定なら、`audio/musicbox.wav`が再生されます。
- `wave!stop`  
    音声を再生停止し、切断します。

### 同梱している音声
[audio](./audio)ディレクトリに三角波や音楽のサンプルwavファイルがあります。  
なお、`musicbox.wav`は[みゅうーさんのフリーWave](https://www.ne.jp/asahi/music/myuu/wave/wave.htm)にあるものです。

## 移植方法
自分のBotに移植したい場合、`WavAudio`クラスを最低限移植すれば大丈夫です。
このクラスがwavファイルを再生できる、`discord.AudioSource`の実装です。
なお、`WavAudio`は`audioop-lts`に依存しているので、それを依存関係に追加する必要があります。

これを使えば、`discord.VoiceClient`のplay関数に渡してwavファイルを再生できます。
例：
```python
vc = await message.author.voice.channel.connect()

f = open("music.wav", "rb")

vc.play(WavAudio(f), after=lambda _: f.close())
```

## License
このリポジトリのコードは[Unlicense](./LICENSE)のライセンスに基づいて許諾されています。
