prompt: peers v1

Target: named peer banks used in the loan-to-deposit comparison. The record key is the peer bank name as printed. Use the same key for every fact about the same peer.

Fields: institution_name (as printed), location (city/state as printed), assets_stated (as printed with units), ltd_ratio_stated (the peer's average loan-to-deposit ratio as printed). Omit anything not printed. If the evaluation gives only a combined peer figure and no named peers, return an empty array.
