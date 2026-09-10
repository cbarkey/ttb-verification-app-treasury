# Sample batches

Drop either ZIP into **Upload a batch** on the running app.

| File | What it shows |
|------|---------------|
| `sample_batch_ok.zip` | 6 rows from the realistic corpus — 3 `PASS`, 3 `FAIL` (brand mismatch, ABV mismatch, reworded warning). Pre-flight is clean; the queue sorts the three exceptions to the top; **Review** walks them with next/prev. |
| `sample_batch_issues.zip` | A deliberately broken manifest so the **pre-flight reconciliation** screen has something to report: a row pointing at an image that isn't in the ZIP, a duplicate serial number, declared values that won't parse (`alcohol_content = TBD`, `net_contents = a jug`), a bad `commodity`, and an orphan image with no manifest row. 3 rows are still fine, so you can proceed and process those. |

Regenerate them after changing the corpus:

```bash
python -m samples.build
```
