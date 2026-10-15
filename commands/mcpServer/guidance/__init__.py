# Copyright (c) Fusion-Essentials contributors
# Dual-licensed under the MIT and Apache-2.0 licenses; see LICENSE-MIT and LICENSE-APACHE.

"""Load and render the authored guidance data without native API imports.

The loader supplies sys_get_guidance records; resources serves the rendered Markdown.
The generator writes the same document to the repository and optionally exports a skill package.
"""
