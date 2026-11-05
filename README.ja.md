[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

![iDex — みんなスキャンしよう！](docs/images/banner.png)

# iDex

iPhone Duo 用のポケットサイズのポケモン図鑑。カメラを向けてスキャンしたら、オーキド博士から研究費が出たつもりで冒険へ。

ネイティブ SwiftUI · English / 简体中文 / 日本語 · デバイス内 Core ML

## このアップグレード版について

これは、[Zihang Huang による iDex](https://github.com/zihang-huang/iDex) をもとに rom0718 がアップグレードした版です。アプリの元のデザインとコードは Zihang Huang の作品であり、このフォークはそれを土台に拡張し、元の MIT ライセンスと各種通知をそのまま引き継いでいます。この版で追加した内容：

- **全国図鑑に対応。** オリジナルのカントー地方 151 種から、第1〜第9世代の全 1025 種に拡張。データは PokéAPI から取得し、不足している中国語・日本語の図鑑テキストはポケモン公式サイトで補っています。No.650 以降のスプライトは Pokémon Showdown の第5世代風スプライトを使用しています。
- **検索できる図鑑一覧。** 名前・番号・タイプで検索、世代で絞り込み、世代見出しはスクロールしても上部に表示、グリッドとリストを切り替え可能。開き直すと前回見ていた位置に戻ります。
- **鳴き声ボタン。** 図鑑の「読み上げ」の隣で、そのポケモンの鳴き声だけを再生できます。
- **1025 種を識別するモデル。** ゲームのスプライトと公式イラスト、カード画像、3 つの公開データセットで EfficientNet-B0 を再学習しました。学習に使っていないテスト画像での正解率は 93.8%（カードは 89.6%）。実際のカメラでの精度はこれより低い可能性があり、まだ測定していません。詳しくは[モデルの説明](iDex/Recognition/MODEL.md)をご覧ください。
- **厳格モードとエンジョイモード。** 設定 → 識別モード。詳しくは下の「オーキド博士くらい正確？」をご覧ください。
- **クレジットの更新。** 設定 → クレジットとドキュメントに、新しく加えたデータ・スプライト・音声・学習データの出典をすべて記載しました。
- **クラウドビルド。** GitHub Actions でアプリのビルドとテストを行い、macOS ランナー上でモデルを書き出します。

## ちょっとフィールドワークへ

| スキャンする | 英語で読む | 简体中文 | 日本語 |
| :---: | :---: | :---: | :---: |
| <img src="docs/screenshots/scanner-result-en.png" width="200" alt="内蔵モデルでピカチュウのサンプルを識別した英語のスキャン画面"> | <img src="docs/screenshots/record-en.png" width="200" alt="タイプ、たかさ、おもさ、図鑑説明を表示したピカチュウの英語の図鑑"> | <img src="docs/screenshots/record-zh.png" width="200" alt="リザードンの簡体字中国語の図鑑"> | <img src="docs/screenshots/record-ja.png" width="200" alt="リザードンの日本語の図鑑"> |

すべて iPhone Duo シミュレータの実際の画面です。ピカチュウはサンプルと明示され、内蔵モデルで識別されます。撮影にあたり、野生のポケモンにはご迷惑をおかけしていません。

[スキャン前の画面](docs/screenshots/scanner-sample-en.png) · [図鑑を検索](docs/screenshots/catalog-search-en.png)

## バッグの中身は？

- **全国図鑑の1025種すべてのポケモン。** ピクセルスプライト、種族値、図鑑説明、鳴き声を収録。図鑑は世代別に絞り込み・検索できます。
- **カメラでも、読み込んだ写真でも。** 識別は iPhone 内で行い、写真はメモリ上にのみ保持します。
- **画面を開くと、研究スペースも広がります。** 内側の画面では、スキャナの隣に図鑑パネルが表示されます。
- **English・简体中文・日本語に対応。** 全1025種の名前、説明、タイプ、能力名を各言語で表示。名前・番号・タイプで検索でき、インストール済みのシステム音声で読み上げます。
- **発見の記録はローカルに保存。** アプリを閉じても進捗は残ります。研究費は想像のままです。

## 言語を選ぶ

**設定 → 言語**で **English**、**简体中文**、**日本語**から選べます。初回起動時は、システムの優先言語のうち対応しているものを使い、その後は選択を保存します。画面の文言、アクセシビリティラベル、図鑑の内容、読み上げが選択した言語に切り替わります。名前は3言語のどれでも検索でき、タイプは選択中の言語で検索できます。読み上げには iOS にインストール済みの音声を使います。

## 使ってみる

**Xcode 27.1** と **iOS 27 以降**が必要です。ヒンジの状態監視には iOS 27.1 の API を使います。

```sh
open iDex.xcodeproj
```

**iDex → iPhone Duo** を選んで実行します。外部パッケージ、API キー、サーバー、実行時のダウンロードは不要です。シミュレータでは**スキャン**をタップしてピカチュウのサンプルを識別できます。実機ではカメラへのアクセスを許可するか、写真を読み込んでください。

テストを実行するには：

```sh
xcodebuild test -project iDex.xcodeproj -scheme iDex \
  -destination 'platform=iOS Simulator,name=iPhone Duo'
```

## オーキド博士くらい正確？

博士からのコメントは、まだ届いていません。モデルは1025種すべてを識別しますが、無関係な物をポケモンと間違えることもあります。スコアは校正済みの確率ではありません。確信度の低い結果は、発見の記録への自動登録や自動読み上げを行いません。実際のカメラの認識精度とヒンジの動作は、引き続き実機での検証が必要です。

**厳格モードとエンジョイモード** 学習したモデルは1つだけです。設定 → 識別モードの2つのモードは、スキャンを「識別完了」（発見済みに登録し自動で読み上げ）とみなすのに必要な確信度だけが異なります。どちらのモードでも、スキャン後には最有力候補が表示されます。

| | 厳格モード（既定） | エンジョイモード（オリジナル設定） |
| --- | --- | --- |
| 判定ルール | 温度 0.75 でスコア 95% 以上、かつ1位と2位のロジット差 3 以上（検証データで選定） | スコア 25% 以上、かつロジット差 0.5 以上 |
| テスト画像のうち自動識別された割合 | 75.8% | 93.4% |
| そのうち正解の割合 | 99.7% | 97.4% |
| 日常の写真をポケモンと誤認した割合 | 3.1% | 40.6% |

厳格モードは発見の記録をきれいに保てますが、再スキャンを求められることが多くなります。エンジョイモードは、向けたものをほぼ何でもポケモンとして識別します（ポケモンでない物も含みます）。数値は学習に使っていないテスト画像（ポケモン画像 12,449 枚、COCO の日常写真 64 枚）によるもので、実際のカメラでの測定ではありません。

## 中をのぞくと

SwiftUI、AVFoundation、Core ML、システム音声。すべてローカルで動作します。

以下の技術資料は英語です：

[開発ガイド](docs/development.md) · [モデルの説明](iDex/Recognition/MODEL.md) · [パフォーマンス](docs/performance.md) · [スクリーンショットと画像素材](docs/images/README.md)

## ライセンス

iDex 独自のアプリのソースコードと関連スクリプトには [MIT ライセンス](LICENSE)を適用します。著作権表示は Copyright (c) 2026 Zihang Huang です。適用範囲と除外対象は [NOTICE.md](NOTICE.md)をご覧ください。

同梱モデルは MIT の対象外です。学習済みモデルへの貢献について貢献者が保有する権利は、[モデルに関する通知](iDex/Recognition/MODEL_NOTICE.md)に記載された範囲で CC BY-NC-SA 4.0 により提供されます。ポケモンのコンテンツと外部の学習データセットも MIT の対象外です。[素材のクレジット](iDex/Catalog/ATTRIBUTION.md)もご確認ください。同梱フォントには引き続き [Press Start 2P](iDex/Resources/Fonts/PressStart2P-OFL.txt) と [Fusion Pixel](iDex/Resources/Fonts/FusionPixel-OFL.txt) の OFL ライセンスを適用します。

## 人間のみなさん、ありがとう

オリジナルのアプリ：[Zihang Huang](https://github.com/zihang-huang/iDex)。スプライト：[Pokémon Database](https://pokemondb.net/sprites)、No.650 以降は [Pokémon Showdown](https://play.pokemonshowdown.com/sprites/gen5/)。データと鳴き声：[PokéAPI](https://github.com/PokeAPI/pokeapi)。不足していた中国語・日本語の図鑑：[pokemon.cn](https://www.pokemon.cn/play/pokedex/)、[ポケモンずかん](https://zukan.pokemon.co.jp/)。学習画像：[PokeAPI sprites](https://github.com/PokeAPI/sprites)、[Pokémon TCG API](https://pokemontcg.io/)、Hugging Face の 3 つのデータセット、COCO の背景写真（[モデルに関する通知](iDex/Recognition/MODEL_NOTICE.md)）。モデル：[TorchVision](https://docs.pytorch.org/vision/stable/models/efficientnet.html) を用いてローカル学習した EfficientNet-B0（FP32）。フォント：Press Start 2P、Fusion Pixel（SIL OFL 1.1）。

[素材のクレジット](iDex/Catalog/ATTRIBUTION.md) · [モデルの出典](iDex/Recognition/MODEL.md)

非公式のファンプロジェクトです。ポケモンおよび関連する権利は、任天堂、クリーチャーズ、ゲームフリーク、The Pokémon Company に帰属します。iDex は各社との提携や公認を受けていません。
