This distribution contains the Project Copilot agent and a bundled Needle engine for Windows x64.

Quick usage

Windows (PowerShell or CMD):

	.\run_copilot.bat "list all files in C:\Aarav" --verbose

Unix / macOS (if applicable):

	./run_copilot.sh "list all files in /path/to/folder" --verbose

Direct Python invocation

	python -m agent.copilot "list all files in C:\Aarav" --verbose

Notes

- This bundle includes the Python `needle` package and the native engine binary for Windows x64 (`needle/libneedle.dll`).
- Recipients with only a basic Python installation can run the agent offline without additional pip installs for the agent functionality shown here.
- If you need support for other platforms (Linux, macOS, or Windows ARM), ask for a multi-platform bundle; the engine binaries for those platforms must be included separately.

Troubleshooting

- If the agent attempts to download the engine, ensure `dist/needle/libneedle.dll` exists. If missing, run `build_engine_windows.py` from the project root to fetch and extract the engine wheel (internet required for that step).
- For advanced model features (finetuning, JAX-backed inference), recipients will need to install heavy ML dependencies (see project `requirements.txt`).

Contact

For packaging questions or adding platform binaries, open an issue or ask the packager.
