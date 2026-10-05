"""The public DTC material the ISO 20022 adapter was built from, pinned (ORDER SC-1, WP-4).

EXPERIMENTAL (charter section 18.6). Metadata only: no DTC document and no
schema file is reproduced in this repository.

WHAT IS PINNED, AND WHY
-----------------------
DTC (the Depository Trust Company) publishes its corporate action ISO 20022
material on its Corporate Actions Technical Documentation Hub, as one package
per business area and standards release. Every package this adapter was built
from is recorded here with the URL it was retrieved from, the DTG (date-time
group, UTC, ``YYYYMMDDHHMM``) of retrieval, and the SHA-256 of the bytes
received. Inside each package, the one XSD the adapter's profile was read from
is recorded by its path in the package and its own SHA-256.

A reader can fetch the same URL, hash it, and know whether DTC has changed it
since. A changed hash means the profile in
:mod:`~atreides.corporate_actions.iso20022` may no longer match, not that it
does not.

WHY NO SCHEMA FILE IS COMMITTED
-------------------------------
Bill decided on 5 October 2026 that no ISO 20022 schema is vendored for this
order (order section 6, item 1). The adapter therefore validates against a
structural profile derived from these XSDs, and says structural validation,
never schema validation. Tests can check emitted messages against the XSDs
themselves where a reader has downloaded them and points
``DTC_CA_XSD_DIR`` at them; the hashes below are what those files must match.

The hub also publishes data dictionaries for each release. The adapter's
profile was not read from them, so they are not pinned here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import Field

from atreides.customer_protection.common import Frozen
from atreides.customer_protection.rules.model import DTG_PATTERN

__all__ = [
    "DTC_PACKAGES",
    "DTC_XSDS",
    "HUB_URL",
    "DtcPackage",
    "DtcXsd",
    "MessageFamily",
    "Release",
]

#: Where every package below was found.
HUB_URL: Final = (
    "https://www.dtcc.com/products-and-services/asset-services/"
    "corporate-actions-processing/ca-documentation"
)

_RETRIEVED: Final = "202610051734"
_SHA256 = r"^[0-9a-f]{64}$"


class Release(StrEnum):
    """The SWIFT standards release a DTC message profile belongs to."""

    SR2025 = "SR2025"
    SR2026 = "SR2026"


class MessageFamily(StrEnum):
    """The ISO 20022 corporate action messages this adapter handles."""

    #: seev.031, Corporate Action Notification: the announcement.
    ANNOUNCEMENT = "announcement"
    #: seev.033, Corporate Action Instruction: an election.
    INSTRUCTION = "instruction"
    #: seev.035, Corporate Action Movement Preliminary Advice.
    MOVEMENT_PRELIMINARY_ADVICE = "movement_preliminary_advice"
    #: seev.036, Corporate Action Movement Confirmation.
    MOVEMENT_CONFIRMATION = "movement_confirmation"


class DtcPackage(Frozen):
    """One DTC package as retrieved."""

    package_id: str
    title: str
    release: Release
    url: str = Field(pattern=r"^https://files\.dtcc\.com/")
    retrieved_dtg: str = Field(pattern=DTG_PATTERN)
    sha256: str = Field(pattern=_SHA256)


class DtcXsd(Frozen):
    """One XSD inside a pinned package: the source of one message profile."""

    release: Release
    family: MessageFamily
    package_id: str
    path_in_package: str
    #: The ISO 20022 message identifier, which is also the XML namespace's last part.
    message_id: str = Field(pattern=r"^seev\.\d{3}\.\d{3}\.\d{2}$")
    sha256: str = Field(pattern=_SHA256)


def _package(package_id: str, title: str, release: Release, url: str, sha256: str) -> DtcPackage:
    return DtcPackage(package_id=package_id, title=title, release=release, url=url,
                      retrieved_dtg=_RETRIEVED, sha256=sha256)


_BASE = "https://files.dtcc.com/download/assets/"

DTC_PACKAGES: Final[tuple[DtcPackage, ...]] = (
    _package("announcements-2025", "Announcements (SR2025)", Release.SR2025,
             _BASE + "Announcements-2025.zip/20630d66b08d11f18bad1e308cb92e47",
             "4738f2b3e4c6e08bc56885ef301b3ff9d3e9392404717396d5ab51d634e26092"),
    _package("announcements-2026", "Announcements (SR2026)", Release.SR2026,
             _BASE + "Announcements-2026.zip/17d5c3beb08d11f1af0f6e0ff2ab1254",
             "afa392c7e4214ad4cd0a87eba82360f3a432f4bcfb6f8c2fd5e8c60acbdb1500"),
    _package("elective-dividend-instructions-2025",
             "Elective Dividend Instructions (SR2025)", Release.SR2025,
             _BASE + "Elective+Dividend+Instructions-2025.zip/1b6afc88b08d11f1a3f96e0ff2ab1254",
             "04c4668a467c46995a7848f2411c1eeb8cdc47ef6e4015ef39ce48dffcc94ade"),
    _package("elective-dividend-instructions-2026",
             "Elective Dividend Instructions (SR2026)", Release.SR2026,
             _BASE + "Elective+Dividend+Instructions-2026.zip/180b4bbab08d11f1b21f36954d8bd163",
             "6224a554ce1c4804e8d559bf548eeb7d159251898f542cc917afd04f045f505b"),
    _package("entitlements-and-allocations-2025",
             "Entitlements and Allocations (SR2025)", Release.SR2025,
             _BASE + "Entitlements+and+Allocations-2025.zip/25ce74a2b08d11f1a912fa5ff415476b",
             "2f328cbdfd6dbb8332e30aab221648791eb2ef2157808c132e45496c0bd4f5fb"),
    _package("entitlements-and-allocations-2026",
             "Entitlements and Allocations (SR2026)", Release.SR2026,
             _BASE + "Entitlements+and+Allocations-2026.zip/1d9a5a80b08d11f18bb91e308cb92e47",
             "c879d9dc55f72ba5f69f43eb13b3060c7034017ac030d6a432481e2d6d4149e8"),
)


def _xsd(release: Release, family: MessageFamily, package_id: str, path: str,
         message_id: str, sha256: str) -> DtcXsd:
    return DtcXsd(release=release, family=family, package_id=package_id,
                  path_in_package=path, message_id=message_id, sha256=sha256)


_A, _I, _E = "Announcements/", "Elective Dividend Instructions/", "Entitlements and Allocations/"
_F = MessageFamily

DTC_XSDS: Final[tuple[DtcXsd, ...]] = (
    _xsd(Release.SR2025, _F.ANNOUNCEMENT, "announcements-2025",
         _A + "SR_2025_Corporate_Action_Notification_seev_031_001_15.xsd", "seev.031.001.15",
         "ce504227291852e3597a0b57c61fc74912871c423f2fa0ad1f2e261842545a9d"),
    _xsd(Release.SR2026, _F.ANNOUNCEMENT, "announcements-2026",
         _A + "SR_2026_Corporate_Action_Notification_seev_031_001_16.xsd", "seev.031.001.16",
         "b00dc7a9acd32854ba6b968db7edddf759091e2836e04cec7d394473d8fa2033"),
    _xsd(Release.SR2025, _F.INSTRUCTION, "elective-dividend-instructions-2025",
         _I + "SR_2025_Corporate_Action_Instruction_seev_033_001_13.xsd", "seev.033.001.13",
         "e05ead3cad90d2cd4155a05328022afe2d28178d6d0ef64f9feaf4aa89f32c85"),
    _xsd(Release.SR2026, _F.INSTRUCTION, "elective-dividend-instructions-2026",
         _I + "SR_2026_Corporate_Action_Instruction_seev_033_001_14.xsd", "seev.033.001.14",
         "0a56fc5c1f82c5ed2ad8031b090670260a3341d4da8cd14bea6791b4041ab25f"),
    _xsd(Release.SR2025, _F.MOVEMENT_PRELIMINARY_ADVICE, "entitlements-and-allocations-2025",
         _E + "SR_2025_Corporate_Action_Movement_Preliminary_Advice_seev_035_001_16.xsd",
         "seev.035.001.16",
         "2dd52d532d143e01a308d1dbc181be0ed7cd540fe295c363b8c9fadee0eb8336"),
    _xsd(Release.SR2026, _F.MOVEMENT_PRELIMINARY_ADVICE, "entitlements-and-allocations-2026",
         _E + "SR_2026_Corporate_Action_Movement_Preliminary_Advice_seev_035_001_17.xsd",
         "seev.035.001.17",
         "ac288ff92288e099c79d97d0689858b0e147f97a6fce0862c6295cfd715f60b5"),
    _xsd(Release.SR2025, _F.MOVEMENT_CONFIRMATION, "entitlements-and-allocations-2025",
         _E + "SR_2025_Corporate_Action_Movement_Confirmation_seev_036_001_16.xsd",
         "seev.036.001.16",
         "e8b2d8a3ec5dd13486febcc3f12a90258c1cb6780a70775e863a6da059837585"),
    _xsd(Release.SR2026, _F.MOVEMENT_CONFIRMATION, "entitlements-and-allocations-2026",
         _E + "SR_2026_Corporate_Action_Movement_Confirmation_seev_036_001_17.xsd",
         "seev.036.001.17",
         "249c8b27a3a3671e4389faeaec9eb413c26b4771a9da8fe56daa219bd72aeb5b"),
)
