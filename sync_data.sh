#!/bin/bash

# Auto-sync script for updating trading data to GitHub
# Run this after your data collector updates the CSV file

echo "🔄 Syncing trading data to GitHub..."

# Navigate to repo directory (in case script is run from elsewhere)
cd "$(dirname "$0")"

# Add the CSV file
git add data/trading_results.csv

# Check if there are changes to commit
if git diff --staged --quiet; then
    echo "✅ No changes to sync - CSV is already up to date"
    exit 0
fi

# Commit with timestamp
git commit -m "Update trading data $(date '+%Y-%m-%d %H:%M:%S')"

# Push to GitHub
git push

if [ $? -eq 0 ]; then
    echo "✅ Data synced successfully!"
    echo "📊 Streamlit Cloud will auto-deploy in ~30 seconds"
else
    echo "❌ Failed to push to GitHub"
    echo "Please check your internet connection and GitHub credentials"
    exit 1
fi
