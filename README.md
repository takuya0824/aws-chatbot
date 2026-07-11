# AWS Bedrock Chatbot

シンプルなAWSチャットボット。

## デモ

[デプロイ手順](#セットアップ手順)に従えば数分で同じ構成を再現できます。

## 技術スタック

| レイヤー | 技術 |
|---|---|
| フロントエンド | HTML / CSS / Vanilla JavaScript |
| バックエンド | Python (AWS Lambda) |
| LLM | Amazon Bedrock（Claude Haiku 4.5, Converse API） |
| データベース | DynamoDB（会話履歴、オンデマンド課金 + TTLで自動削除） |
| API | API Gateway (HTTP API) |
| ホスティング | S3 + CloudFront |
| IaC | AWS CDK (Python) |
| 認証 | なし |

## アーキテクチャ構成図

[architecture.drawio](./architecture.drawio) を [draw.io](https://app.diagrams.net/) で開いて確認できます。

## ディレクトリ構成

```
aws-chatbot/
├── frontend/               # 静的チャットUI（ビルド不要）
│   ├── index.html
│   ├── script.js           # チャット送受信・セッションID管理
│   └── style.css
├── backend/
│   └── lambda/
│       └── app.py          # Bedrock Converse API 呼び出し + DynamoDB履歴の読み書き
├── infra/                  # AWS CDK (Python)
│   ├── app.py              # CDKアプリのエントリポイント（リージョン指定など）
│   ├── infra_stack.py      # DynamoDB / Lambda / API Gateway / S3 / CloudFront定義
│   ├── cdk.json
│   └── requirements.txt
└── README.md
```

## コスト最適化のポイント

- Lambda / API Gateway (HTTP API) / DynamoDB (オンデマンド) はいずれも従量課金で、低トラフィックならほぼ無料枠内
- Claude Haiku 4.5 は Bedrock 上で最も安価な現行モデル
- DynamoDBの会話履歴はTTLで自動削除（ストレージコストが積み上がらない）
- CloudFrontは`PriceClass_200`（北米・欧州・アジア・中東・アフリカ）に限定（日本からのアクセスを想定し、南米・オセアニアのエッジは除外してコストを抑制）
- API Gatewayにスロットリング（10 req/s, burst 20）を設定し、認証なしでも料金の急増を抑制
- S3バケットはリソース削除時に自動でオブジェクトも削除される設定（`cdk destroy`でクリーンに片付く）
- 予算アラートはアカウント全体で月$10のAWS Budgetsをすでに設定済み（このスタック側では重複作成しない）

## セットアップ手順

### 1. 事前準備

- AWSアカウントと、デプロイ権限を持つIAMクレデンシャル（`aws configure`済み）
- Node.js（`npm install -g aws-cdk` 用。未インストールでも`npx`経由で代用可）
- Python 3.12 と `pip`
- **Bedrockのモデル利用準備（初回のみ・アカウントごとに1回）**
  - 「Model access」ページでの事前有効化は不要（モデルは初回呼び出し時に自動的に有効化される）
  - ただし**Anthropicモデルは初回利用時に利用目的（use case）フォームの入力が必須**。
    未入力の状態で呼び出すと `ResourceNotFoundException: Model use case details have not
    been submitted for this account.` というエラーになる（実際にハマったポイント。詳細は
    [トラブルシューティング](#トラブルシューティング実際にハマったポイント)参照）
  - AWSコンソール（リージョン: 東京）→ Amazon Bedrock → 「Model catalog」→
    **Claude Haiku 4.5** を開き、Playgroundなどで一度呼び出そうとすると利用目的フォームが表示されるので入力・送信する
  - 反映まで最大15分程度かかる

### 2. AWSインフラのデプロイ（AWS CDK）

以下は実際にローカル環境からデプロイした際に使用したコマンドです
（`<AWS_ACCOUNT_ID>` は自分のAWSアカウントIDに読み替えてください）。

```bash
# AWS CLI / Node.js / Python が使えるか確認
which aws node python3
aws --version

# AWS認証情報が有効か確認（アカウントIDやIAMユーザーが表示されればOK）
aws sts get-caller-identity
```

```jsonc
// 出力例（値はダミー）
{
  "UserId": "AIDAEXAMPLE1234567890",
  "Account": "<AWS_ACCOUNT_ID>",
  "Arn": "arn:aws:iam::<AWS_ACCOUNT_ID>:user/your-iam-user"
}
```

`aws configure` が未設定の場合は、先にIAMユーザー（またはSSO）のクレデンシャルを設定してください。

```bash
# Python仮想環境の作成とCDK依存パッケージのインストール
cd infra
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

CDK CLI（`cdk`コマンド）をグローバルインストールしていない場合は、`npx`経由でそのまま実行できます
（`npm install -g aws-cdk` 済みなら以下の `npx --yes aws-cdk@2` は単に `cdk` に読み替え可）。

```bash
# テンプレートが正しく合成できるか確認（AWSへの変更は発生しない）
npx --yes aws-cdk@2 synth

# 初回のみ：CDKが使うS3バケット等をアカウント・リージョンに作成
npx --yes aws-cdk@2 bootstrap aws://<AWS_ACCOUNT_ID>/ap-northeast-1

# 実際にデプロイ（承認プロンプトをスキップする場合は --require-approval never）
npx --yes aws-cdk@2 deploy --require-approval never
```

デプロイが完了すると、以下がターミナルに出力されます。

```text
Outputs:
AwsChatbotStack.ApiURL = https://xxxxxxxxxx.execute-api.ap-northeast-1.amazonaws.com/chat
AwsChatbotStack.SiteURL = https://xxxxxxxxxxxxxx.cloudfront.net
AwsChatbotStack.TableName = AwsChatbotStack-ChatHistoryTableXXXXXXXX-XXXXXXXXXXXX
```

- `SiteURL` — チャット画面のCloudFront URL（ブラウザでこれを開く）
- `ApiURL` — Lambdaを呼び出すAPIエンドポイント
- `TableName` — DynamoDBテーブル名

フロントエンドはS3+CloudFrontへの`BucketDeployment`でCDKが自動的にアップロードするため、
別途ビルド・デプロイコマンドを実行する必要はありません（`config.js`に`ApiURL`がデプロイ時に自動注入されます）。

### 3. 動作確認

`SiteURL`をブラウザで開くだけで動作します（静的サイトなのでローカルビルドは不要）。

フロントエンドを経由せず、APIエンドポイントを直接curlで叩いて疎通確認もできます。

```bash
curl -s -X POST "<ApiURLの値>" \
  -H "Content-Type: application/json" \
  -d '{"message": "こんにちは、自己紹介してください"}'
```

正常なら次のようなJSONが返ります。

```json
{"session_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", "reply": "こんにちは！..."}
```

同じ`session_id`を指定して再度送信すると、会話履歴（DynamoDB）を踏まえた応答になっているか確認できます。

```bash
curl -s -X POST "<ApiURLの値>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<上で返ってきたsession_id>", "message": "さっき何て自己紹介した？"}'
```

### 4. 削除（コストをかけたくない場合）

```bash
cd infra
source .venv/bin/activate
npx --yes aws-cdk@2 destroy --force
```

（`--force`は削除確認プロンプトをスキップするオプション。対話的に確認しながら進めたい場合は外してよい）

削除には数分かかります（CloudFrontディストリビューションの無効化待ちが最も時間がかかる）。
完了後、以下のコマンドでスタックが消えたことを確認できます。

```bash
aws cloudformation describe-stacks --stack-name AwsChatbotStack --region ap-northeast-1
# → "Stack with id AwsChatbotStack does not exist" と出ればOK
```

#### `cdk destroy`で削除されるもの

- DynamoDB テーブル（会話履歴）
- Lambda 関数
- API Gateway（HTTP API）
- CloudFront ディストリビューション
- S3 バケット（`auto_delete_objects=True`のため中身のオブジェクトも自動削除される）

#### `cdk destroy`では削除されない・手動対応が必要なもの

このスタックの管理外にあるため、`cdk destroy`を実行しても以下は残る。

| 項目 | 内容 | 対応方法 |
|---|---|---|
| **CDK bootstrap用リソース** | `CDKToolkit`スタック、S3ステージングバケット、ECRリポジトリ | `cdk deploy`とは別ライフサイクル。放置してもコストはごくわずかだが、CLIで完全削除する手順は下記参照 |
| **LambdaのCloudWatch Logsロググループ** | CDKのLambda L2コンストラクトはロググループをCloudFormation管理下に置かないため残存する | CloudWatch Logsコンソール、または`aws logs delete-log-group`で手動削除 |
| **BedrockのAnthropicモデルに対するAWS Marketplaceサブスクリプション** | 初回呼び出し時に`aws-marketplace:Subscribe`権限で自動サブスクライブされたもの（[トラブルシューティング](#トラブルシューティング実際にハマったポイント)の3番目参照） | アカウントレベルの契約なので`cdk destroy`の対象外。解約する場合はAWS Marketplaceコンソール →「Manage subscriptions」から手動解除 |

#### CDK bootstrap用リソースをCLIで完全削除する手順

`CDKToolkit`スタックはCloudFormationの通常スタックなのでCLIから削除できるが、
S3ステージングバケットとECRリポジトリには`DeletionPolicy: Retain`が設定されているため、
スタック削除だけでは残る（実際に確認済み）。特にS3バケットは**バージョニングが有効**なので、
中身を消したつもりでも旧バージョンや削除マーカーが残り、`aws s3 rb`が
`BucketNotEmpty`で失敗する点に注意。

```bash
BUCKET="cdk-hnb659fds-assets-<AWS_ACCOUNT_ID>-ap-northeast-1"
REGION="ap-northeast-1"

# 1. バケットを空にする（通常の削除。ただし旧バージョンは残る）
aws s3 rm "s3://$BUCKET" --recursive --region "$REGION"

# 2. CDKToolkitスタックを削除（S3バケット・ECRリポジトリはRetainのため残る）
aws cloudformation delete-stack --stack-name CDKToolkit --region "$REGION"
aws cloudformation wait stack-delete-complete --stack-name CDKToolkit --region "$REGION"

# 3. S3バケットに残った全バージョン・削除マーカーを列挙して削除
aws s3api list-object-versions --bucket "$BUCKET" --region "$REGION" \
  --output json --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' > /tmp/versions.json
aws s3api list-object-versions --bucket "$BUCKET" --region "$REGION" \
  --output json --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' > /tmp/markers.json
aws s3api delete-objects --bucket "$BUCKET" --region "$REGION" --delete file:///tmp/versions.json
aws s3api delete-objects --bucket "$BUCKET" --region "$REGION" --delete file:///tmp/markers.json

# 4. 空になったバケット自体を削除
aws s3 rb "s3://$BUCKET" --region "$REGION"
```

ECRリポジトリ（`cdk-hnb659fds-container-assets-<AWS_ACCOUNT_ID>-ap-northeast-1`）は、
イメージをpushしていなければ`CDKToolkit`スタック削除と同時に消えることを確認済み
（残っていた場合は`aws ecr delete-repository --force`で削除する）。

削除後、このアカウント・リージョンで再度CDKを使う場合は`cdk bootstrap`からやり直しになる。

## トラブルシューティング（実際にハマったポイント）

デプロイ自体は成功しても、Bedrockの呼び出しでつまずくことがあります。実際に遭遇したエラーと対処法です。

### 1. `on-demand throughput isn't supported` エラー

```json
{"error": "model invocation failed: An error occurred (ValidationException) when calling
the Converse operation: Invocation of model ID anthropic.claude-haiku-4-5-20251001-v1:0
with on-demand throughput isn't supported. Retry your request with the ID or ARN of an
inference profile that contains this model."}
```

**原因**: 東京リージョン（`ap-northeast-1`）では、Claude Haiku 4.5をfoundation-modelの
bare ID（`anthropic.claude-haiku-4-5-20251001-v1:0`）でオンデマンド呼び出しできない。
**クロスリージョン推論プロファイル**（この構成では日本ジオの`jp.anthropic.claude-haiku-4-5-20251001-v1:0`、
東京・大阪にルーティングされる）経由で呼び出す必要がある。

**対処**: `infra/infra_stack.py`で
- LambdaのモデルID環境変数を`jp.anthropic.claude-haiku-4-5-20251001-v1:0`に変更
- IAMポリシーのリソースに、推論プロファイルARN（`arn:aws:bedrock:{region}:{account}:inference-profile/{profile_id}`）と、
  ルーティング先リージョン（東京・大阪）それぞれのfoundation-model ARNの両方を許可

対応済みなので、このリポジトリのコードをそのまま使う場合は追加対応不要です。

### 2. `Model use case details have not been submitted for this account` エラー

```json
{"error": "model invocation failed: An error occurred (ResourceNotFoundException) when
calling the Converse operation: Model use case details have not been submitted for this
account. Fill out the Anthropic use case details form before using the model."}
```

**原因**: Anthropicモデルは、AWSアカウントごとに初回利用時の「利用目的（use case）」申告フォームの
提出が必須。未提出だと（一度は通っても）以降のリクエストがこのエラーで弾かれる。

**対処**: [事前準備](#1-事前準備)の手順を参照。AWSコンソール（東京リージョン）→ Amazon Bedrock →
「Model catalog」→ Claude Haiku 4.5 を開いて呼び出そうとすると表示されるフォームに、
会社名（個人利用なら氏名や`Individual`でも可）・Webサイト（GitHub/LinkedInのURLなどでも可）・
利用目的を入力して送信する。反映まで最大15分程度かかるため、送信後すぐにリトライしても
同じエラーになる場合がある（時間をおいて再試行する）。

### 3. `AccessDeniedException ... aws-marketplace:ViewSubscriptions, aws-marketplace:Subscribe` エラー

```json
{"error": "model invocation failed: An error occurred (AccessDeniedException) when calling
the Converse operation: Model access is denied due to IAM user or service role is not
authorized to perform the required AWS Marketplace actions (aws-marketplace:ViewSubscriptions,
aws-marketplace:Subscribe) to enable access to this model."}
```

**原因**: Anthropicモデルは内部的にAWS Marketplace経由の製品として提供されており、
初回呼び出し時にアカウント全体の自動サブスクリプションが発生する。この処理には
呼び出し元（この構成ではLambdaの実行ロール）に`aws-marketplace:ViewSubscriptions` /
`aws-marketplace:Subscribe`の権限が必要（この2アクションはリソース指定不可のため
`Resource: "*"`で許可する）。前述の「use caseフォーム提出」を済ませても、この権限がなければ
別エラーとして引き続き弾かれる。

**対処**: このリポジトリでは`infra/infra_stack.py`のLambda実行ロールに以下のポリシーを
追加済みなので対応不要。

```python
chat_fn.add_to_role_policy(
    iam.PolicyStatement(
        actions=[
            "aws-marketplace:ViewSubscriptions",
            "aws-marketplace:Subscribe",
        ],
        resources=["*"],
    )
)
```

一度サブスクリプションが成立すればアカウント全体で有効になるため、以降はこの権限がなくても
呼び出し自体は可能になる（が、剥奪する理由もないため付与したままにしている）。

## 改善点

今回の開発で複雑さを避けるために妥協した点。後続対応の参考として記載する。

### セキュリティ

| 項目 | 現状 | 推奨対応 |
|---|---|---|
| API認証 | なし（誰でも呼び出し可能） | Amazon CognitoやAPIキーによる認証を追加 |
| コスト防御 | API Gatewayのスロットリングのみ（10 req/s, burst 20の固定値） | AWS WAFの導入や使用量プラン（Usage Plan）による柔軟な制御 |
| CORS設定 | Lambda・API Gatewayとも`allow_origins=["*"]` | CloudFrontドメインのみに絞る |
| Marketplace権限の範囲 | `aws-marketplace:Subscribe`等をLambda実行ロールに`Resource:"*"`で恒常付与（アクション上リソース指定不可のため） | 初回サブスクライブ成立後は権限を剥奪する運用も検討可能 |

### アーキテクチャ

| 項目 | 現状 | 推奨対応 |
|---|---|---|
| 会話履歴の保持期間 | TTLで一律1日 | ユーザー・用途に応じて可変にする、セッション終了時の明示的な削除 |
| 利用モデル | Claude Haiku 4.5に固定 | 用途に応じてSonnetなど別モデルへ切り替えられる設計 |
| リージョン構成 | 東京リージョン固定（推論プロファイルにより大阪にも自動ルーティング） | 複数リージョンでの冗長化やフェイルオーバーは未考慮 |
| レスポンス方式 | Converse APIによる一括応答（ノンストリーミング） | `ConverseStream` APIで逐次表示に対応し体感速度を改善 |

### 開発・運用

| 項目 | 現状 | 推奨対応 |
|---|---|---|
| CI/CD | なし（手動で`cdk deploy`を実行） | GitHub ActionsとOIDC認証によるデプロイ自動化 |
| ログ管理 | Lambdaの CloudWatch Logs のみ（ロググループはCDK管理外で自動削除もされない） | サブスクリプションフィルタやX-Rayトレーシングの追加 |
| テスト | なし | Lambdaハンドラーの単体テスト、CDKのスナップショット/アサーションテスト |
| Bedrock/Claude Platform on AWSの切り替え | 未実装（Bedrock固定） | フロントにトグルを追加し、裏側のクライアント実装を切り替えられるようにする |
