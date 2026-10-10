# ASR bake-off

Compares the cloud WhisperX transcripts the pipeline uses today with two local
engines, scoring each through the production matcher. The finding is in
[docs/findings/asr-bakeoff.md](../../docs/findings/asr-bakeoff.md).

| Runner | Engine | Timestamps |
|---|---|---|
| (none) | WhisperX on Replicate — the saved `*_whisperx_raw.json` files | WhisperX's own |
| `run_nemo.py` | `nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0`, RNNT or CTC decoder | the model's own |
| `run_sherpa.py` | the same NVIDIA model through sherpa-onnx (`--model-dir` from `tools/export_local_model`) | the model's own token times, grouped into words |
| `run_cohere.py` | `CohereLabs/cohere-transcribe-arabic-07-2026` | wav2vec2 forced alignment (WhisperX's Arabic aligner) |

Every runner writes the WhisperX raw shape, so `score.py` runs
`qurantext recitation-match` / `lecture-match` on each and compares the
results.

## Environments

Each engine needs its own venv (NeMo and transformers 5 pin different stacks).
CPU-only torch is enough:

    python3 -m venv venv-nemo
    venv-nemo/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    venv-nemo/bin/pip install "nemo_toolkit[asr]" soundfile

    python3 -m venv venv-cohere
    venv-cohere/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    venv-cohere/bin/pip install "transformers>=5.4" accelerate soundfile librosa sentencepiece

The Cohere model is gated: accept its terms on the Hugging Face model page, then
`venv-cohere/bin/hf auth login` with a read token. It needs about 4.5 GB of RAM.

## Running

    BAKE=/some/dir    # one folder per engine; clip names as in score.py CLIPS
    mkdir -p $BAKE/whisperx
    cp output/recitation_matching/furquanTra7-11_recitation_whisperx_raw.json $BAKE/whisperx/furquanTra7-11.json
    cp output/recitation_matching/alFurqanCut_recitation_whisperx_raw.json    $BAKE/whisperx/alFurqanCut.json
    cp output/lecture_matching/الفرقان7-11-final_lecture_whisperx_raw.json      $BAKE/whisperx/lecture7-11.json

    venv-nemo/bin/python   run_nemo.py   input/recitations/furquanTra7-11.mp3 $BAKE/nemo-rnnt/furquanTra7-11.json
    venv-cohere/bin/python run_cohere.py input/recitations/furquanTra7-11.mp3 $BAKE/cohere/furquanTra7-11.json
    # ... same for alFurqanCut.mp3 and lectures/الفرقان7-11-final.wav

    venv/bin/python prototypes/asr_bakeoff/score.py $BAKE   # project venv

`gate.py $BAKE <engine>` checks an engine against spec §0 of the local
transcription engine design (exit 0 = pass).

`score.py --list` prints every clip with its audio path, for looping the
runners over all 17 Al-Furqān recordings (`qurantext transcribe --audio … --output
$BAKE/whisperx/<clip>.json` for the WhisperX side). A clip an engine has no
transcript for is skipped. Matching a full-surah recitation takes about 16
minutes and is single-threaded, so run the `*-match` commands in parallel
before scoring: `score.py` reuses any `*_match.json` it finds.
