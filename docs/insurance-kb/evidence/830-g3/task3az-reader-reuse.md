# Task3az reader reuse — delivery pending

User observed slow field and original-PDF clicks. Measured old requests: scope0.955s +1,058,707B/516-member directory2.290s +field0.740s +catalog0.484s; PDF authority3.736s and file2.851s, excluding render. Earlier cold samples70.61s directory and80.16s field remain unprofiled; these changes do not prove cold backend cost resolved. No LLM execution on these read paths.

Mounted reader retains one exact release directory but obtains a fresh backend field response before display. Each citation still obtains/validates fresh authority, with one source PDF document reused only for matching immutable scope/release/candidate/source/revision binding/hash/page count. Retention threshold16MiB is input-file size, not a decoded-memory guarantee. Clear on error/identity change/unmount; lease cleanup defers disposal until users release. No global/persistent cache or API changes.

RED: task3az-directory-red-02.log3FAIL10PASS; task3az-pdf-red-02.log2FAIL3PASS; task3az-viewer-red.log2FAIL24PASS. GREEN: task3az-viewer-green-02.log44PASS10.11s; reader regression14PASS with PDF worker import environment failure; temporary Vitest allow-existing-worktree-dependencies config resolves that environment, task3az-port-regression.log1PASS3.31s. No production configuration changed for tests. Independent frozen UI10files manifest0765bf96d9fde469faa59667c965acdb5aa5d5a7fe66f9f1f07cb3a344ff9977, review task3az-independent-review-01.md0BLOCKER. Runtime build/deployment and actual browser latency NOT RUN yet. G3 not complete.

PDF v6 installed type declarations expose destroy on PDFDocumentLoadingTask, not PDFDocumentProxy. Type-check caught this real cleanup error before deploy; task3az-port-close-red-02.log proves zero destroy calls (1FAIL1PASS), changed to loadingTask.destroy including failed-open cleanup. task3az-port-close-green.log46PASS5.54s. Frozen02 manifest675f189b86ef94585ed8aa98c32337d880607a93761c00c8cdf9357a7463b12b; only port adapter/test differ from frozen01, remaining UI unchanged. Type-check rerun pending.

Frozen02 independent review0BLOCKER, reportSHA e685cbc5438158b9150b90b0925576827aff2bf586a6215d6182b08075768050. Runtime RouterView has no fullPath remount key; same-component directory reuse is applicable to actual navigation.

Final npm run type-check PASS (exit0), task3az-typecheck-02.log. All affected software checks closed before commit/build.

Live deployment: Task3az02 UI source79c1d8b873a5fc2a9ca81338a143ae12486d523f image75d617210fd20fcb3cb60d9bc4c604c48936f6432429cfe4b50f0adefe6ccc0e PASS16:05:56Z; runtime nginx read verified. Prior image403 EACCES failed and rolled back (task3az-ui-rollback-verification.json PASS). Permanent public-asset modes repaired via Dockerfile, same compiled bytes reused, zero additional Vite builds.

Real clicks confirmed field navigation uses one field GET and repeat source viewing avoids another PDF-content GET. Backend still4.999/4.528s fields; one repeated preview46.469s. Another new-release preview11.119s. These are server durations, not click-to-render measurements. Optimization only partially resolves the user issue; backend latency remains open. No assertion of model/parse work on these G3 serving paths.
