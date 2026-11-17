"""Read-only Image Playground hAI selection API compatibility."""
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

api = importlib.import_module(ROOT.name + ".playground_api")


def bundle(root, mode):
    directory = Path(root) / mode / "collections" / "test"
    directory.mkdir(parents=True)
    items=[]
    for i in range(3):
        name=f"{i+1:03d}.txt"
        (directory/name).write_text("Picture [[SUBJECT]] "+str(i+1),encoding="utf-8")
        items.append({"prompt_id":f"p-{mode}-{i+1}", "file":f"collections/test/{name}",
                      "collection":"Test Group","collection_slug":"test",
                      "source_character":"Alice","source_model":"nano-banana-2",
                      "source_index":i})
    manifest={"schema_version":2,"mode":mode,"subject_deferred":True,
              "subject_placeholder":"[[SUBJECT]]",
              "prompt_count":len(items),"items":items}
    (directory.parent.parent/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")


class ImagePlaygroundSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for mode in ("t2i","i2i"):
            bundle(self.temp.name,mode)
        patch=mock.patch.dict("os.environ",{"HAI_PROMPT_LIBRARY_ROOT":self.temp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_lists_collections_and_counts(self):
        info=api.collections()
        self.assertEqual(info["totals"]["t2i"],3)
        self.assertEqual(info["collections"][0]["name"],"Test Group")
        self.assertEqual(info["collections"][0]["counts"]["i2i"],3)

    def test_subject_replacement_and_deterministic_random(self):
        selection={"mode":"t2i","subject":"sH1VX woman",
                   "collection":"Test Group","count":2,"selection":"random","seed":31}
        a=api.select(selection)
        self.assertEqual(a,api.select(selection))
        self.assertEqual(len(a["selected"]),2)
        self.assertTrue(all("[[SUBJECT]]" not in x["text"] for x in a["selected"]))
        self.assertTrue(all("sH1VX woman" in x["text"] for x in a["selected"]))

    def test_exact_prompt_id_and_invalid_params(self):
        result=api.select({"mode":"i2i","subject":"woman",
                           "selection":"prompt_id","prompt_id":"p-i2i-2"})
        self.assertEqual(result["selected"][0]["id"],"p-i2i-2")
        self.assertEqual(result["selected"][0]["text"],"Picture woman 2")
        with self.assertRaises(ValueError):
            api.select({"mode":"t2i","subject":"","count":2})
        with self.assertRaises(ValueError):
            api.select({"mode":"t2i","subject":"woman","count":201})
        with self.assertRaises(ValueError):
            api.select({"mode":"t2i","subject":"woman",
                        "selection":"prompt_id","prompt_id":""})


if __name__=="__main__":
    unittest.main()
