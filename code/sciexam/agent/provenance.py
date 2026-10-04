"""Fingerprints of what the formal runs executed, for checking a rerun against the record.

HARNESS_SHA256 is the sha256 of the harness file each ranked run executed (run_meta
provenance.harness.sha256, keyed by runs.csv campaign_id). The seven versions differ only in
the Claude subscription and Codex adapters. The prompts, the lifecycle constants and the
orchestration are identical across all seven, and this package reproduces them.

TASK_FILES_SHA256 is the sha256 of every file the agents received in their workspace (the
task tree of the formal runs, freeze manifest grading.task_inputs plus the data and paper
files). The released dataset carries the same bytes for every file. It does not carry the
raw data or the reference paper, which the user rebuilds or obtains.
"""

HARNESS_SHA256 = {
    "formal6-20260910": "52b87870abf3641d8849698db21f1df475b01f61fae0f65e4b044bf6341364a5",
    "formal6B-20260910": "7637b28577875518257cb8e07c83b6afb2ba68ba3fb9677368a0d1e16dd38a85",
    "formal6C2-20260911": "d055af53130ac8e0937e60c0b9092efa95099ff51a5e6b11d520f731b4e68a2e",
    "formal6H-20260912": "2a351dd9e563ca1b2cee0cd75df4dc41292e1c7aa6686743e5154d2db3dbe931",
    "formal6J-20260913": "3e97b5f6de26b9a5991230389b1cc1facdbc5dac9cb0f76f40bb54a05440ead0",
    "formal6L-20260913": "232ad486660725c59cb15bccd38621ebdb212eb79cbdd7df20c362a1cb6d9f78",
    "formal6N-20260915": "b03430c85245855655b26175ed3c74237a2e1c92e536f58054df928d56c2275a",
}

# Harness of the three Claude Fable 5.1 condition runs (run_meta provenance.harness.sha256;
# the year-anonymised run executed it through a wrapper that replaced only the Phase 1 gate).
# Against the formal6N-20260915 version it differs in the task tree selection, the tool
# envelope profile, the CA variables of the egress environment and a task hash event; the
# prompts, the lifecycle constants and the orchestration are identical.
CONDITION_HARNESS_SHA256 = {
    "formal6W-20260918": "fa5e6da89cb65854d284ed0f412abe2deab906a7482b4c81ee5d37cce304bbd6",
    "formal6X-20260920": "fa5e6da89cb65854d284ed0f412abe2deab906a7482b4c81ee5d37cce304bbd6",
    "anonY6-20260921": "fa5e6da89cb65854d284ed0f412abe2deab906a7482b4c81ee5d37cce304bbd6",
}

# Workspace files of the formal runs. Paths are relative to the workspace root.
TASK_FILES_SHA256 = {
    "instruction.md": "1a7ef3e09004ede198b89fc182b702c6f0f9458f7d0fb6b52256751baed19d58",
    "interface.md": "b35f38cc8cbc9e8ce7810ef2d43388a6654a8918981115ddb14b2b798b1e06d9",
    "data_processing.md": "316a4aceecc79a3564818b739f07ff176520ce9bed0287fa935ff1826ef15eda",
    "nondim_scales.json": "2ad29cb5d075d8f860b9ff46745277a61430fa5b1505879ac8d5c8cc84cf7e89",
    "blacklist.txt": "1eaf91f426c523f475ac048aced3b9ec97e01be5ede358a9c800f205d3d1351f",
    "papers/README.md": "7bb966424d9ad3cb8f61d0be7b9fc3e88544daccdda78889fc2b2f32a0b7af4c",
    "papers/Jin_1997_Recharge_Oscillator_Part1_ConceptualModel_JAS.pdf":
        "1744dc982436ba76217846e813b67aab6143a4d3d029a00aa4ed840b9c243be3",
    "data/ersst_sst.nc": "7d8c22751b3c8368bcf0abef8e6d9b54fd8d1ecc86587b4d0b6d7bd99340fb79",
    "data/godas_pottmp.nc": "8943a1213f1f8361f3411b5d250dbb3697ead2ec862d28b3c72c81996110002b",
    "data/godas_ucur.nc": "8ab855eca039c599f720bdcc9b2313d17b476f34b96bfb1ef4d6a28baa707645",
    "data/ncep_uwnd850.nc": "b465805fe60c11eb036d55ae839dcf8b40c8628709d775fbc0cee8e34ca90e92",
}

# Workspace files of the three condition runs (the task_prompt event at the top of each
# trajectory), and the task tree hash over them: sha256 of the sorted "path sha256" lines.
_SHARED = {k: TASK_FILES_SHA256[k] for k in (
    "blacklist.txt", "nondim_scales.json", "papers/README.md",
    "papers/Jin_1997_Recharge_Oscillator_Part1_ConceptualModel_JAS.pdf")}
_WEB = dict(_SHARED, **{k: TASK_FILES_SHA256[k] for k in (
    "interface.md", "data_processing.md", "data/ersst_sst.nc", "data/godas_pottmp.nc",
    "data/godas_ucur.nc", "data/ncep_uwnd850.nc")})
CONDITION_FILES_SHA256 = {
    "web_literature_and_data": dict(
        _WEB, **{"instruction.md": "20e25cdaee98f55b5268d5be9c31fb8c513b405dfb8dcf5cb0b5ee0132ff8249"}),
    "web_literature_only": dict(
        _WEB, **{"instruction.md": "379ad39b47ccda6d1aabb72eed04d426a446b666137056ffd8eb619a1d7492d9"}),
    "years_anonymised": dict(_SHARED, **{
        "instruction.md": TASK_FILES_SHA256["instruction.md"],
        "interface.md": "965ef47f43a2ba1f2cd4831c9905ed04aad9a00b33bbb7b8848dbd7257ebb5b0",
        "data_processing.md": "a24debd18120aacb09838c398a8deae302ae6fbf1a7addd3c5f6bc5fcc6de328",
        "data/sst_monthly.nc": "452b10e127c7f93d07787ba3dc80cac58d4b9803848cfa9195f36c5a504a76de",
        "data/ocean_pottmp_monthly.nc":
            "9502344e58c1327babd6f7b695ab92f75a697dcae452b439c649895e8c23bffc",
        "data/ocean_ucur_monthly.nc":
            "00866081d340a3bffc7ec817f613817af9e0646c3316bf98de757a141da2ebb6",
        "data/wind850_daily.nc": "91166c34982f6d648e9020780aed93234abf509e9ad8b16f5eadd90c0e050d92"}),
}
CONDITION_TREE_SHA256 = {
    "web_literature_and_data": "e066be86c2f026e07d5967a2b1998725b07862d26143e0448231f35eff5bf5d1",
    "web_literature_only": "4e6180b1c0f98ce0e152a4cb94ceca715079d69c3c58055da1155579771d3377",
    "years_anonymised": "eb3af309a5ff45b7df04e532c6724115ab9c84f306d4460e61a1a371af1c8ca3",
}

# Files of the dataset's task/ folder that were never in an agent workspace.
NOT_GIVEN_TO_AGENTS = ("scripts/", "papers/CITATION.md")

# The raw data and the paper are not redistributed. These names are what the workspace
# must contain, exactly as the formal runs had them.
DATA_FILES = ("ersst_sst.nc", "godas_pottmp.nc", "godas_ucur.nc", "ncep_uwnd850.nc")
PAPER_FILE = "Jin_1997_Recharge_Oscillator_Part1_ConceptualModel_JAS.pdf"
