"""CLI command: bitbucket:publish-changes — fast lane for reviewer 'changes requested' (~1m)."""
from __future__ import annotations

import argparse

from ..channel import LANE_CHANGES
from ._loop import configure_lane_parser, execute_lane


class BitbucketPublishChangesCommand:
    @property
    def name(self) -> str:
        return "bitbucket:publish-changes"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Detect reviewer 'changes requested' on open Bitbucket PRs and publish prioritized jobs"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        configure_lane_parser(parser)

    def execute(self, args: argparse.Namespace) -> None:
        execute_lane(LANE_CHANGES, args)
