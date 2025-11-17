# DH

## What is OMPL?

Open Motion Planning Library（OMPL）は、サンプリングベースのモーションプランニングアルゴリズムを体系的に集めたオープンソースライブラリです。プランナーの実装に特化しており、環境表現・干渉チェック・可視化などは意図的に含まず、MoveIt や OMPL.app など別フレームワークへ容易に統合できる構造になっています（`ompl/doc/markdown/mainpage.md.in`）。PRM や RRT 系をはじめ多様なプランナー、各種状態空間・サンプラ、最適化目的を備えており、ROS/MoveIt を通じた産業ロボットの軌道生成から教育用途まで幅広く利用されています。

## TODO

[] `ompl_doc` をベースにした RAG ドキュメントアシスタントを構築し、研究者が API リファレンスやチュートリアル、デモを会話形式で検索できるようにする。
[] プランナーのレシピ検索機能を追加し、デモコードや代表的な設定ファイルをインデックス化してプランナー／状態空間／目的関数で絞り込める実行可能スケルトンを返す。
[] 引用情報を自動整理し、OMPL 関連文献の参照箇所と BibTeX エントリをセットで提示できるシステムに拡張する。
[] ロボット構成や拘束、目的関数から適切なプランナーと推奨パラメータを提案し、C++／Python のスタータースニペットを生成するレコメンドウィザードを試作する。



## How to Setup

### LLMのLocal API endpointを建てる

1. ollamaをinstall
```
curl -fsSL https://ollama.com/install.sh | sh
```
2. モデルのDownload
   1. 今回は2つ、`gpt-oss:20b`と`deepseek-r1:8b` を使用
   ```
   ollama pull ${MODEL_NAME}
   ```

3. start ollama model
```
ollama run ${MODEL_NAME}
```

4. (optional) stop ollama model
```
ollama stop ${MODEL_NAME}
```

### Python 仮想環境（uv + venv）

> git clone 直後に最低限必要な手順です。

1. uv を持っていない場合のみインストール。
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
2. リポジトリ直下で仮想環境を作成（キャッシュ先は任意のローカルパスで OK）。
   ```bash
   UV_CACHE_DIR=.uv-cache uv venv .venv
   ```
3. 仮想環境を有効化し、`pyproject.toml`/`uv.lock` に記載された依存を同期する。
   ```bash
   source .venv/bin/activate
   UV_CACHE_DIR=.uv-cache uv sync
   ```
   ※ `uv sync` は初回と依存更新時のみ。以降は `source .venv/bin/activate` だけで利用可能。
4. 追加でパッケージを入れる場合は `uv add <package>` を使う。  
   - 本プロジェクトでは埋め込みに `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`、ベクトル DB として Chroma を利用。



### DoxygenからOMPLのドキュメントを生成する手順

1. git clone git@github.com:ompl/ompl.git

1. 事前準備  
   - `doxygen` と `graphviz` をインストールする（例: `sudo apt install doxygen graphviz`）。  
   - `boost`, `cmake`, `eigen`, `yaml-cpp` など OMPL の基本依存も揃えておく。
2. ビルド用ディレクトリを用意する。
   ```bash
   cd ompl
   mkdir -p build/doc
   cd build/doc
   cmake ../..
   ```
3. Doxygen ターゲットをビルドする。
   ```bash
   cmake --build . --target ompl_doc -j$(nproc)
   ```
4. 生成結果は `ompl/build/doc/ompl_doc` に出力される。`index.html` をブラウザで開けばオフラインドキュメントを確認できる。
5. ソースを更新した場合も同じ `cmake --build . --target ompl_doc` を実行するだけで差分を再生成できる。




### RAG ドキュメントアシスタントの着手ログ

1. `ompl/doc/markdown` と `ompl/build/doc/ompl_doc` の内容を平文化してチャンク化するスクリプト `scripts/extract_ompl_docs.py` を追加した。
2. 以下のコマンドで JSONL（`rag_data/ompl_doc_chunks.jsonl`）を生成した。必要であれば同じコマンドを再実行してドキュメントの更新を取り込める。
   ```bash
   python3 scripts/extract_ompl_docs.py \
       --html-dir ompl/build/doc/ompl_doc \
       --markdown-dir ompl/doc/markdown \
       --output rag_data/ompl_doc_chunks.jsonl
   ```
   実行結果（例）: `Wrote 19027 chunks from 2556 documents to .../rag_data/ompl_doc_chunks.jsonl`




### ローカル RAG インデックス構築と問い合わせ

1. ベクトルインデックスの作成（Chroma 永続化）  
   ```bash
   python3 scripts/build_local_index.py \
       --chunks rag_data/ompl_doc_chunks.jsonl \
       --persist-dir .chroma \
       --collection-name ompl_docs \
       --model-name sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
       --reset
   ```
   英語のみでqueryする場合
   ```bash
   python3 scripts/build_local_index.py \
    --chunks rag_data/ompl_doc_chunks.jsonl \
    --persist-dir .chroma \
    --collection-name ompl_docs_en \
    --model-name sentence-transformers/all-mpnet-base-v2 \
    --reset
   ```

   - `--reset` で再構築前に既存コレクションを削除。  
   - `--batch-size` や `--model-name` で埋め込み条件を調整。
2. Ollama でホストしている LLM を使って質問  
   ```bash
   python3 scripts/query_local_rag.py \
       "OMPLで推奨される最適化プランナーは？" \
       --ollama-model deepseek-r1:8b \
       --persist-dir .chroma \
       --collection-name ompl_docs
   ```
   - 取得したチャンクと回答が CLI に表示される。  
   - デフォルトは `deepseek-r1:8b`。必要に応じて `--ollama-model gpt-oss:20b` などへ変更可能。`--top-k` でコンテキスト件数も調整できる。
3. サンプルプログラムで一連の流れを確認  
   ```bash
   python3 samples/sample_query.py
   ```
   - 事前に `.venv` を有効化し、Ollama のモデルを起動しておく必要があります。

## Source Code Description

- `scripts/extract_ompl_docs.py`  
  - 目的: OMPL の Doxygen HTML と Markdown を平文化してチャンク化し、RAG 用の JSONL を生成する。  
  - 概要: 依存ライブラリなしの簡易 HTML パーサーでテキスト抽出 → 余分な空白を正規化 → 1,200 文字程度のチャンクに分割（重なりあり） → メタデータ（元ファイル、タイトル、チャンク番号）付きで `rag_data/*.jsonl` に出力。  
  - 実行例: `python3 scripts/extract_ompl_docs.py --html-dir ompl/build/doc/ompl_doc --markdown-dir ompl/doc/markdown --output rag_data/ompl_doc_chunks.jsonl`

- `scripts/build_local_index.py`  
  - 目的: チャンク化済み JSONL を埋め込み、Chroma のコレクションへ永続化する。  
  - 概要: SentenceTransformer によるバッチ埋め込み → `collection.upsert` で `.chroma` に保存。`--reset` でコレクション再作成が可能。  
  - 実行例: `python3 scripts/build_local_index.py --chunks rag_data/ompl_doc_chunks.jsonl --persist-dir .chroma --collection-name ompl_docs --reset`

- `scripts/query_local_rag.py`  
  - 目的: Chroma から関連チャンクを取得し、Ollama 上の LLM（例: `deepseek-r1:8b`）で回答を生成する。  
  - 概要: SentenceTransformer でクエリをベクトル化 → Top-k を取得 → 文脈を整形して Ollama `/api/generate` に送信 → 応答と引用情報を表示。  
  - 実行例: `python3 scripts/query_local_rag.py "OMPLのプランナー一覧を教えて" --ollama-model deepseek-r1:8b`

- `samples/sample_query.py`  
  - 目的: 代表的な RAG 質問フローをまとめて確認できる最小のサンプル。  
  - 概要: `run_query` を呼び出し、決め打ちの質問に対するコンテキストと回答を標準出力へ表示する。  
  - 実行例: `python3 samples/sample_query.py`
