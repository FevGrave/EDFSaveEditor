"""sync_languages.py - Keep languages.json's non-English language blocks in sync with 'en'.

Problem this solves: whenever a new translation key gets added to the app (a new button,
label, note, etc.), it only ever gets added to the 'en' block by hand - nothing enforced that
ja/kr/cn/sc also got that key, so they silently drifted out of sync over time (as of this
script being written, ja/sc were missing 32 keys and kr/cn were missing 40). The app's tr()
already falls back to English for a language missing a key, so nothing breaks at runtime -
but a translator opening languages.json to work on e.g. "kr" has no way to tell a key is
missing entirely versus intentionally left in English, and the key order across files drifts
apart, making the file harder to hand-edit/diff over time.

What this script does, using 'en' as the source of truth:
  1. Reorders every other language's keys to match 'en' key order exactly.
  2. Any key 'en' has that a language is missing gets added, with English text copied in as
     a placeholder - so the translator has real text to work from instead of an empty string
     or a silently-absent key, and the app displays something sensible even before it's
     translated.
  3. Any key a language has that 'en' does NOT have is left alone and kept (appended at the
     end) rather than silently deleted - it's reported so a human can decide whether it's
     leftover cruft or something 'en' is actually missing.
  4. Existing translated values are never touched or overwritten - only missing keys get
     English text, and only key ORDER changes for keys that already existed.

Usage:
    python sync_languages.py            # sync and write languages.json in place
    python sync_languages.py --check    # dry run - report what would change, don't write

Run this after adding any new key to languages.json['languages']['en'], to keep the other
four language blocks structurally in sync (translator can then search the file for English
text sitting where their language should be, and translate it).
"""
import json
import os
import sys
import collections

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
LANGUAGES_JSON_PATH = os.path.join(SCRIPT_DIR, 'languages.json')


def sync_languages(path: str, write: bool = True) -> dict:
    """Reorder/backfill every non-'en' language block in the languages.json at `path` to
    match 'en's key order and key set. Returns a report dict: {lang_code: {'added': [...],
    'orphaned': [...]}}. Writes the result back to `path` unless write=False (dry run)."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    langs = data.get('languages', data)

    if 'en' not in langs:
        raise ValueError("languages.json has no 'en' block to use as the source of truth")
    canonical_order = list(langs['en'].keys())

    report = {}
    for lang_code, lang_dict in langs.items():
        old_order = list(lang_dict.keys())
        new_dict = collections.OrderedDict()
        added = []
        for key in canonical_order:
            if key in lang_dict:
                new_dict[key] = lang_dict[key]
            else:
                new_dict[key] = langs['en'].get(key, key)
                added.append(key)
        orphaned = [k for k in lang_dict if k not in canonical_order]
        for k in orphaned:
            new_dict[k] = lang_dict[k]
        langs[lang_code] = new_dict
        # Track pure reordering separately from added/orphaned - e.g. if 'en' itself gets
        # manually reordered (no keys added/removed anywhere), every other language's keys
        # still need to be physically rewritten to follow the new order, which added/orphaned
        # alone wouldn't reflect in the report (previously showed "already in sync" even
        # though the file was rewritten).
        reordered = added == [] and orphaned == [] and list(new_dict.keys()) != old_order
        report[lang_code] = {'added': added, 'orphaned': orphaned, 'reordered': reordered}

    if write:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return report


def print_report(report: dict, wrote: bool):
    total_added = 0
    total_orphaned = 0
    total_reordered = 0
    for lang_code, info in report.items():
        added, orphaned, reordered = info['added'], info['orphaned'], info.get('reordered', False)
        total_added += len(added)
        total_orphaned += len(orphaned)
        total_reordered += 1 if reordered else 0
        if not added and not orphaned and not reordered:
            print(f"[{lang_code}] already in sync")
            continue
        if not added and not orphaned and reordered:
            print(f"[{lang_code}] no keys added/missing, but key order {'was' if wrote else 'would be'} updated to follow EN's current order")
            continue
        print(f"[{lang_code}] {len(added)} key(s) {'added' if wrote else 'would be added'} from EN"
              f"{', ' + str(len(orphaned)) + ' orphaned key(s) found' if orphaned else ''}")
        if added:
            print(f"    added:    {added}")
        if orphaned:
            print(f"    orphaned: {orphaned}  (kept as-is - not in 'en', check if these are stale or if 'en' is missing them)")
    if total_added == 0 and total_orphaned == 0 and total_reordered == 0:
        print("\nEverything already in sync - no changes needed.")
    else:
        action = "Wrote" if wrote else "Would write"
        print(f"\n{action} {total_added} backfilled key(s) total across all non-English languages.")


if __name__ == '__main__':
    dry_run = '--check' in sys.argv or '--dry-run' in sys.argv
    report = sync_languages(LANGUAGES_JSON_PATH, write=not dry_run)
    print_report(report, wrote=not dry_run)
