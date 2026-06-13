#!/bin/bash
# Synchronize chipfuzz directory from server to local (Linux/Mac version)
# Usage: chmod +x sync_chipfuzz_to_local.sh && ./sync_chipfuzz_to_local.sh

echo "Synchronizing chipfuzz from the remote server..."
scp -r root@your-server-host:/root/ChipFuzzer/chipfuzz ~/Desktop/

if [ $? -eq 0 ]; then
    echo ""
    echo "Synchronization succeeded."
    echo "Files were updated under: ~/Desktop/chipfuzz"
else
    echo ""
    echo "Synchronization failed. Please check:"
    echo "  1. Network connectivity."
    echo "  2. SSH key configuration."
    echo "  3. Remote server address."
fi
