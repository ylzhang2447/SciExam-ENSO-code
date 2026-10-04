# SciExam for ENSO: code and data

Code and data of **SciExam for ENSO: Can AI Agents Build Climate Models?**

Yinling Zhang, Langchen Liu, Dongbin Xiu, Xueyan Zou, Xu Kuang, Mengdi Wang, Shilong Liu

[Website](https://ylzhang2447.github.io/enso-agent-benchmark/) · [Detailed results](https://ylzhang2447.github.io/enso-agent-benchmark/results/) · Paper (arXiv link coming soon)

SciExam-ENSO is a benchmark in which LLM agents build low-order stochastic models of
the El Nino-Southern Oscillation from raw observations within a six-hour budget.

| folder | content | license |
|---|---|---|
| `code/` | the `sciexam` package: grader, regrading, structural ablation, figures, observation rebuild and the agent harness. See `code/README.md` | MIT |
| `dataset/` | the released records: runs, checkpoints, agent-built models, simplified models, grader observations and task files. See `dataset/README.md` | CC BY 4.0, with third-party terms listed in `dataset/LICENSE.md` |

## Quickstart

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e code                        # Python 3.10 or newer; grading also needs Docker
sciexam download --local dataset           # checks the sha256 of every data file
sciexam grade --split final --jobs 5       # regrades the 12 final models and the reference model
sciexam grade-sample dataset/models/final/claude-fable-5.1 --in-process   # one model, no Docker
```

Rerunning an agent, grading a new run and rerunning the Claude Fable 5.1 condition runs are
described in `code/README.md`.

## Citation

```bibtex
@article{zhang2026sciexam,
  title  = {SciExam for ENSO: Can AI Agents Build Climate Models?},
  author = {Zhang, Yinling and Liu, Langchen and Xiu, Dongbin and Zou, Xueyan
            and Kuang, Xu and Wang, Mengdi and Liu, Shilong},
  year   = {2026}
}
```

Contact: Shilong Liu (slongliu86@gmail.com)
