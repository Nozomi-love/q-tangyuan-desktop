# 内置合成音效

四个音效由pet_window.py的synthesize_sound使用Python标准库wave、math和struct生成，不使用外部录音：

- poke.wav：柔和下降水滴音。
- eat.wav：开心咀嚼双音节。
- coin.wav：收益/成就叮当音。
- music_box.wav：约6秒的原创轻柔琶音。

单声道、22050Hz、16bit PCM WAV；使用QSoundEffect播放。运行时仅生成缺失文件，已有音频不覆盖。HUD与右键/托盘静音同步，状态存在玩家本地存档，不随仓库上传。
