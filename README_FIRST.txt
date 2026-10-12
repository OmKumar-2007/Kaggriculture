FARMCRAFT: SAFE RESET + 50 TEAM TESTING (MAIN PROJECT)

This is an UPDATE to your existing FarmCraft_50_Full_Rehearsal folder.
It does not replace your 50 benchmarked agents, runtime state, or other project files.

1) Close the currently running launcher (choose 0).
2) Extract the update ZIP to:
   D:\kaggriculture\Kaggriculture
   Confirm overwrite of Start-50-Team-Test.ps1.
3) Run from Windows PowerShell:

   cd D:\kaggriculture\Kaggriculture
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-50-Team-Test.ps1

4) Menu:
   1 Check protection and current phase
   2 Reset old test qualification + delete only QA26_B2C9C5_01..20
   3 Register 50 teams, upload 50 bots, run 100 real sandboxes, verify analytics
   4 Submit 50 automated official Round 1 attempts (YOU start Round 1 in Admin)
   5 Observe final tournament (YOU finalize and launch Round 2 in Admin)
   6 Snapshot and report
   0 Exit

MENU OPTION 2:
  - Prompts for organizer password once for preflight.
  - Requires pg_dump and pg_restore executable client tools, compatible with Neon PostgreSQL.
  - Prompts once for Neon database connection string securely, never writes its secret to disk.
  - Checks that the API and direct Neon database agree on team temp and ALL reference hashes.
  - Refuses active jobs and existing historical tournament_games.
  - Prints a dry-run deletion plan of only old QA26_B2C9C5 teams.
  - Takes a full PostgreSQL custom-format dump in existing kit's runtime folder.
  - Uses pg_restore --list to validate archive inventory and SHA-256 checksum.
  - Requires an explicit final confirmation before a transactional reset/deletion.
  - Updates competition_state to SETUP, resets tournament_state to initial registration and event flags to DEVELOPMENT.
  - Deletes only exact 20-name QA team records, their sandbox/jobs and their official claims.
  - Re-verifies protected temp submissions and all reference metadata before committing.
  - Never deletes object-storage blobs; old QA Redis presence records may expire later.

NOTES:
- The 19 non-QA teams (based on last snapshot) remain: this is NOT a blanket database wipe.
- Old official evaluation records for unrelated accounts remain as history, but the new Round 1 starts with a new timestamp.
- If active jobs or historical tournament games exist, the tool STOPS; no destructive changes happen.
- A custom-format dump is a backup, but keep/verify it and do not commit it to Git.
- The direct database operation is NOT available from the public website, so local Neon access is required.
- No changes have been made to the live database by preparing this update.
- The new Python reset script has not been executed against your Neon database.
