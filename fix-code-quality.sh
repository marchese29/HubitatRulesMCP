#!/bin/bash

# Script to auto-fix code quality issues

echo "🔧 Auto-fixing code quality issues..."

echo "📋 Running ruff linter with auto-fix..."
uv run --group dev ruff check . --fix

echo "🎨 Auto-formatting code with ruff..."
uv run --group dev ruff format .

echo "🔍 Running mypy to check remaining type issues..."
uv run --group dev mypy .

echo "✅ Code quality fixes completed!"
echo "Note: Some issues may require manual fixes, especially type annotations."
