.PHONY: install run stop run-listener run-ui

# Use uv to install dependencies defined in pyproject.toml
install:
	uv pip install .

# Run the listening service
run-listener:
	uv run python listening_service/main.py

# Stop the listening service
stop-listener:
	pkill -f 'python listening_service/main.py' || true

# Run the UI service (using uvicorn for development)
run-ui:
	uv run uvicorn ui.main:app --host 0.0.0.0 --port 8000 --reload --app-dir .

# Stop the UI service (finds uvicorn running ui.main:app)
stop-ui:
	pkill -f 'uvicorn ui.main:app' || true

# Convenience targets (might need adjustment for backgrounding/terminal splitting)
run:
	@echo "Running listener and UI. Use 'make stop' to stop both."
	@echo "It's often easier to run them in separate terminals: make run-listener & make run-ui"
	make run-listener &
	make run-ui &

stop:
	make stop-listener
	make stop-ui 