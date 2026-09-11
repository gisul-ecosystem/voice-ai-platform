#!/bin/bash
# Laptop 1 -- LLM node
# Install Ollama first: https://ollama.com/download

ollama pull qwen3:4b-instruct-2507-q8_0
ollama serve &
sleep 2

echo "Ollama running on http://0.0.0.0:11434"
echo "OpenAI-compatible endpoint: http://0.0.0.0:11434/v1/chat/completions"
echo "Test with:"
echo "curl http://localhost:11434/v1/chat/completions -d '{\"model\":\"qwen3:4b-instruct-2507-q8_0\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}'"
