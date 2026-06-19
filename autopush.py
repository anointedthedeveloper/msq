"""
Git Auto-Push Script
Constantly watches for unpushed commits and pushes them automatically.
Does not create new commits - only pushes existing ones.

Usage:
    python autopush.py
"""

import subprocess
import sys
import time


def run_command(cmd, check=True):
    """Run a command and return the result."""
    try:
        result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr
    except subprocess.CalledProcessError as e:
        return e.returncode, e.stdout, e.stderr


def get_unpushed_commits():
    """Get the number of commits that are ahead of the remote."""
    returncode, stdout, stderr = run_command(["git", "rev-list", "--count", "--left-only", "@{u}..HEAD"])
    if returncode != 0:
        return 0
    return int(stdout.strip()) if stdout.strip() else 0


def push_commits(branch):
    """Push commits to remote."""
    returncode, stdout, stderr = run_command(["git", "push"], check=False)
    return returncode, stdout, stderr


def main():
    print("=" * 60)
    print("Git Auto-Push Script (Watching Mode)")
    print("=" * 60)
    
    # Check if we're in a git repository
    returncode, stdout, stderr = run_command(["git", "rev-parse", "--git-dir"])
    if returncode != 0:
        print("ERROR: Not in a git repository")
        sys.exit(1)
    
    # Get current branch
    returncode, stdout, stderr = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if returncode != 0:
        print("ERROR: Could not get current branch")
        sys.exit(1)
    branch = stdout.strip()
    print(f"Current branch: {branch}")
    
    # Set upstream if not configured
    returncode, stdout, stderr = run_command(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if returncode != 0:
        print(f"Setting upstream to origin/{branch}...")
        returncode, stdout, stderr = run_command(["git", "push", "-u", "origin", branch], check=False)
        if returncode != 0:
            print(f"WARNING: Could not set upstream: {stderr}")
        else:
            print(f"✓ Upstream set to origin/{branch}")
    
    print("\nWatching for unpushed commits...")
    print("Press Ctrl+C to stop\n")
    
    check_interval = 5  # seconds between checks
    
    try:
        while True:
            unpushed = get_unpushed_commits()
            
            if unpushed > 0:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Found {unpushed} unpushed commit(s)")
                
                # Pull first to avoid conflicts
                returncode, stdout, stderr = run_command(["git", "fetch"], check=False)
                if returncode == 0:
                    # Check if we're behind
                    returncode, stdout, stderr = run_command(["git", "rev-list", "--count", "--right-only", "@{u}..HEAD"])
                    behind = int(stdout.strip()) if stdout.strip() and returncode == 0 else 0
                    
                    if behind > 0:
                        print(f"  Pulling {behind} remote commit(s)...")
                        returncode, stdout, stderr = run_command(["git", "pull", "--rebase"], check=False)
                        if returncode != 0:
                            print(f"  WARNING: Pull failed: {stderr}")
                
                # Push commits
                returncode, stdout, stderr = push_commits(branch)
                
                if returncode == 0:
                    print(f"  ✓ Pushed {unpushed} commit(s)")
                else:
                    print(f"  ✗ Push failed: {stderr}")
                    print(f"  Retrying in {check_interval} seconds...")
            else:
                # Quiet mode - only show output every minute
                if int(time.time()) % 60 == 0:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] No unpushed commits (watching...)")
            
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        print("\n\nStopped by user")
        print("=" * 60)
        print("Done!")
        print("=" * 60)


if __name__ == "__main__":
    main()
