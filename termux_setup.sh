#!/data/data/com.termux/files/usr/bin/bash
# StudioCLI — Termux setup for Android
# Install Termux from F-Droid (NOT Play Store), then run this script.

set -e
echo "=== StudioCLI Termux Setup ==="

pkg update -y && pkg upgrade -y
pkg install -y python git

pip install rich prompt_toolkit

# Copy aistudio.py to home dir
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/aistudio.py" "$HOME/aistudio.py"

# Create alias
mkdir -p "$HOME/.termux"
cat >> "$HOME/.bashrc" << 'EOF'
alias studio='python ~/aistudio.py'
alias aistudio='python ~/aistudio.py'
EOF

echo ""
echo "Done! Restart Termux, then run: studio"
echo ""
echo "Optional — install python-docx and openpyxl for Beta features:"
echo "  pip install python-docx openpyxl"
