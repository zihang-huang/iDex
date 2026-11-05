[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

![iDex — 把它们都扫描一遍！](docs/images/banner.png)

# iDex

为 iPhone Duo 打造的口袋宝可梦图鉴。对准、扫描，假装大木博士已经批了你的研究经费。

原生 SwiftUI · English / 简体中文 / 日本語 · 设备端 Core ML

## 出门考察一下

| 扫一扫 | 英文图鉴 | 简体中文 | 日本語 |
| :---: | :---: | :---: | :---: |
| <img src="docs/screenshots/scanner-result-en.png" width="200" alt="英文扫描界面通过内置模型识别皮卡丘样本"> | <img src="docs/screenshots/record-en.png" width="200" alt="皮卡丘的英文图鉴，包含属性、身高、体重与观察记录"> | <img src="docs/screenshots/record-zh.png" width="200" alt="喷火龙的简体中文图鉴"> | <img src="docs/screenshots/record-ja.png" width="200" alt="喷火龙的日文图鉴"> |

以上均为 iPhone Duo 模拟器的真实截图。皮卡丘是明确标注的模拟器样本，使用内置模型进行识别。拍摄期间，没有野生宝可梦受到打扰。

[扫描之前](docs/screenshots/scanner-sample-en.png) · [搜索图鉴](docs/screenshots/catalog-search-en.png)

## 背包里有什么？

- **全国图鉴全部1025种宝可梦。** 像素图、基础能力、观察记录，还有叫声；图鉴可按世代筛选和搜索。
- **拍照扫描，也能导入照片。** 识别在 iPhone 上完成，照片仅保留在内存中。
- **展开屏幕，研究空间更大。** 内屏会在扫描器旁显示图鉴面板。
- **English、简体中文和日本語。** 全1025种宝可梦均有本地化名称、描述、属性和能力标签。可按名称、编号或属性搜索，并用已安装的系统语音朗读。
- **本地发现记录。** 关闭应用后，进度依然保留。研究经费依然只是想象。

## 选择语言

打开**设置 → 语言**，选择 **English**、**简体中文**或 **日本語**。首次启动会采用系统偏好中受支持的语言，之后会记住你的选择。界面、无障碍标签、图鉴内容和朗读会随所选语言切换。名称支持跨三种语言搜索，属性搜索则使用当前语言。朗读使用 iOS 上已安装的语音。

## 开始使用

需要 **Xcode 27.1** 和 **iOS 27 或更新版本**。铰链状态观察使用 iOS 27.1 API。

```sh
open iDex.xcodeproj
```

选择 **iDex → iPhone Duo**，然后运行。无需配置第三方依赖、API 密钥、服务器或运行时下载。在模拟器中，轻点**扫描**即可识别皮卡丘样本。在真机上，请允许相机访问，或导入一张照片。

运行测试：

```sh
xcodebuild test -project iDex.xcodeproj -scheme iDex \
  -destination 'platform=iOS Simulator,name=iPhone Duo'
```

## 有大木博士那么准吗？

大木博士暂未回应。模型认识全部1025种宝可梦，但仍可能把无关物体误认为宝可梦；设置里可选「严格」（默认）或「宽松」识别门槛。分数不是经过校准的概率；低置信度结果不会自动计入发现记录，也不会自动朗读。真实相机的识别准确度与物理铰链行为仍需真机验证。

## 打开外壳看看

SwiftUI、AVFoundation、Core ML 和系统语音。所有处理均在本地完成。

以下技术文档为英文：

[开发指南](docs/development.md) · [模型说明](iDex/Recognition/MODEL.md) · [性能](docs/performance.md) · [截图与图形资源](docs/images/README.md)

## 许可证

iDex 的原创应用源代码及配套脚本采用 [MIT 许可证](LICENSE)，版权所有 (c) 2026 Zihang Huang。适用范围和排除项见 [NOTICE.md](NOTICE.md)。

打包模型不适用 MIT；贡献者对训练模型贡献所持权利按[模型声明](iDex/Recognition/MODEL_NOTICE.md)中的范围以 CC BY-NC-SA 4.0 提供。宝可梦内容和外部训练数据集也不适用 MIT。另见[资源署名](iDex/Catalog/ATTRIBUTION.md)；内置字体保留 [Press Start 2P](iDex/Resources/Fonts/PressStart2P-OFL.txt) 和 [Fusion Pixel](iDex/Resources/Fonts/FusionPixel-OFL.txt) 的 OFL 许可证。

## 感谢各位人类

像素图：[Pokémon Database](https://pokemondb.net/sprites)。数据与叫声：[PokéAPI](https://github.com/PokeAPI/pokeapi)。模型：使用 [TorchVision](https://docs.pytorch.org/vision/stable/models/efficientnet.html) 本地训练的 EfficientNet-B0（FP32）。字体：Press Start 2P 和 Fusion Pixel（SIL OFL 1.1）。

[完整资源署名](iDex/Catalog/ATTRIBUTION.md) · [模型来源](iDex/Recognition/MODEL.md)

本项目是非官方粉丝作品。宝可梦及相关权利归任天堂、Creatures、GAME FREAK 和 The Pokémon Company 所有。iDex 与这些公司无关联，也未获得其认可。
