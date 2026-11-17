"""プロジェクト内のディレクトリ位置を1か所にまとめる

各モジュールで Path(__file__).parent... を数えると、ファイルを移動したときに
壊れやすいため、ここで一度だけ解決する。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
LOGS_DIR = PROJECT_ROOT / "logs"
