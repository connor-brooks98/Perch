# Model files go here

The classifier expects two files in this directory. They are **not** bundled
with this repo — grab them from the original whosatmyfeeder project (Phase 3):

```
model/
├── model.tflite    # AIY/Coral iNaturalist birds, MobileNet-v2, quantized
└── labels.txt      # matching labels, one species per line
```

## Where to get them

From the `mmcc-xx/whosatmyfeeder` repository, `model/` directory:

- The quantized classifier — a file like
  `mobilenet_v2_1.0_224_inat_bird_quant.tflite`. Rename (or symlink) it to
  `model.tflite`.
- Its labels file — a file like `inat_bird_labels.txt`. Rename to `labels.txt`.

These originate from Google's Coral / AIY birds model, trained on the
iNaturalist bird dataset. Everything runs locally on the Pi — no API, no
per-inference cost.

## Label format

One label per line; the line number is the class index. Coral's file reads:

```
background
Haemorhous mexicanus (House Finch)
Cardinalis cardinalis (Northern Cardinal)
```

`classify.py` parses `Scientific name (Common Name)` into separate fields and
treats any `background` class as "no bird." An optional numeric index prefix
(`0 background`) is also handled.

## Override paths

If you keep the files elsewhere, point the classifier at them with
`MODEL_PATH` and `LABELS_PATH` in your `.env`.
