---
type: Subsystem Doc
title: Running Commands
description: Run shell commands in the sandbox outside the agent turn path.
resource: "https://github.com/Nikhil-Kadapala/HarnessBox/blob/main/packages/sdk/src/harnessbox/sandbox.py"
tags: [sandbox, sdk]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---
# Running Commands

Execute shell commands directly inside the sandbox, bypassing the AI agent. Useful for setup scripts, test runs, build commands, and verification steps.

```python
result = await session.run_command("echo 'Hello from the sandbox!'")
print(result.stdout)  # "Hello from the sandbox!"
```

## CommandResult

Every command returns a `CommandResult`:

| Field | Type | Description |
|-------|------|-------------|
| `stdout` | str | Standard output |
| `stderr` | str | Standard error |
| `exit_code` | int | Process exit code (0 = success) |

```python
from harnessbox import CommandResult

result = await session.run_command("python -c 'print(1+1)'")
assert result.exit_code == 0
assert result.stdout.strip() == "2"
```

## Working Directory

Commands run in the sandbox's working directory, which defaults to the git workspace root if one is configured:

```python
# If workspace is cloned to /home/user/repo
result = await session.run_command("pwd")
print(result.stdout)  # "/home/user/repo"
```

## Error Handling

Commands that fail return a non-zero exit code — they don't raise exceptions:

```python
result = await session.run_command("cat /nonexistent")
if result.exit_code != 0:
    print(f"Failed: {result.stderr}")
```

## Long-running Commands

Commands run to completion. For long-running processes, consider using the agent instead (which can manage background processes) or set appropriate timeouts at the provider level.

```python
# Install dependencies (may take a while)
result = await session.run_command("pip install -r requirements.txt")
assert result.exit_code == 0

# Run the test suite
result = await session.run_command("pytest tests/ -v --timeout=300")
print(result.stdout)
```

## Examples

### Setup Script

```python
commands = [
    "apt-get update && apt-get install -y redis-server",
    "redis-server --daemonize yes",
    "pip install redis",
]
for cmd in commands:
    result = await session.run_command(cmd)
    if result.exit_code != 0:
        raise RuntimeError(f"Setup failed: {result.stderr}")
```

### Build and Test

```python
# Build
build = await session.run_command("npm run build")
if build.exit_code != 0:
    print(f"Build failed:\n{build.stderr}")
else:
    # Test
    test = await session.run_command("npm test")
    print(f"Tests: exit code {test.exit_code}")
    print(test.stdout)
```
