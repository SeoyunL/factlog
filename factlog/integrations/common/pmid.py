#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""What a PMID is, and the one fold that may be applied to it.

The twin of :mod:`factlog.integrations.common.doi`, and deliberately a separate
module because the rule is not the same one. A PMID is by definition a positive
decimal integer, so **the whole value folds**: ``１２３`` is a *spelling* of
``123`` and both name one PubMed record. A DOI has an opaque suffix where
respelling a character would invent a different identifier, so only its prefix
folds. Two rules, two modules; one file holding both would invite a caller to
reach for the half that does not apply.

Like the DOI fold, this **refuses to rewrite what it does not understand**: a
``pmid:`` label or a ``pubmed.ncbi.nlm.nih.gov`` URL left in a hand-edited file
comes back unchanged rather than being turned into something that merely looks
canonical.

Three call sites need this fold, and they are not the same kind of site:

- :func:`~factlog.integrations.common.source_writer.normalize_cross_id` folds a
  **derived comparison key** (#421), and
  :func:`~factlog.integrations.common.provenance.excluded_sources_by_id` folds a
  **lookup key** through it (#428).
- :mod:`factlog.csl` and :mod:`factlog.bibtex` fold an **exported value** (#428),
  because a full-width PMID in CSL JSON or a BibTeX note is not a PMID any
  downstream tool can resolve.

The fold sat privately in ``source_writer`` until the export boundary needed it;
copying three lines there would have been exactly the duplication #410 removed
elsewhere, and the copies could drift apart on the one detail that decides
everything — *when* the fold declines to apply.

Deliberately NOT in :mod:`factlog.text_norm`: that module is the ``Nd`` category
and nothing else, and takes no position on what a caller does with the answer.
"What counts as a PMID" is identifier syntax, not a Unicode fact — the same line
:mod:`~factlog.integrations.common.doi` draws.
"""
from __future__ import annotations

import re

from factlog.text_norm import fold_decimal_digits

# A PMID, ASCII-spelled: decimal digits and nothing else. ``\d`` would behave
# identically here — measured — because this is matched against an already-folded
# value, which by construction holds no ``Nd`` character outside ``[0-9]``. The
# ASCII class is written anyway, so the guard states its own intent instead of
# resting on what the caller happens to have done first.
PMID_RE = re.compile(r"[0-9]+")


def fold_pmid(value: str) -> str:
    """*value* respelled in ASCII digits, when the whole of it is a PMID.

    Folded only when the folded value is entirely ASCII digits; anything else (a
    ``pmid:`` label or a URL left in a hand-edited file, plain junk) is returned
    **unchanged**, for the same reason :func:`~factlog.integrations.common.doi.
    fold_doi_prefix` refuses a head it does not recognise: a value this function
    does not understand must stay as it is rather than be quietly rewritten.

    Note this is stricter than it may look — ``fold_decimal_digits`` is applied
    to the whole string first, so ``１２３abc`` folds to ``123abc``, fails the
    match, and the **original** is returned. A caller never receives a
    half-normalized value.

    No case handling, unlike the DOI fold's callers: a decimal digit has no case,
    and a value with a letter in it is one this function declines anyway.
    """
    folded = fold_decimal_digits(value)
    return folded if PMID_RE.fullmatch(folded) else value
