"""Atlas checks against the actual CSV and image paths, without model startup."""
import hashlib
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from api import app
import herb_catalog as catalog


class CatalogueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)

    def test_all_pages_cover_model_classes(self):
        ids=[]
        for page in range(1,14):
            response=self.client.get("/api/v1/herbs",params={"page":page})
            self.assertEqual(response.status_code,200)
            data=response.json()
            self.assertEqual(data["total"],300)
            self.assertEqual(data["collectionTotal"],300)
            ids.extend(h["id"] for h in data["items"])
        self.assertEqual(ids,[f"tcmp-{n:03}" for n in range(1,301)])
        self.assertEqual(self.client.get("/api/v1/herbs",params={"page":999}).json()["page"],13)

    def test_search_and_combined_filters(self):
        row=catalog.rows()["tcmp-004"]
        detail=catalog.serialize(row,True)
        for name in (row["Chinese Name"],row["Latin Name"],detail["materials"][0]["药材名称"]):
            result=self.client.get("/api/v1/herbs",params={"q":name}).json()
            self.assertIn("tcmp-004",[h["id"] for h in result["items"]])
        for row in catalog.rows().values():
            if row["植物别名"]:
                alias=catalog.split_values(row["植物别名"])[0]
                result=self.client.get("/api/v1/herbs",params={"q":alias,"page_size":60}).json()
                self.assertGreater(result["total"],0)
                break
        region=next(r for r in catalog.REGIONS if r in detail["distribution"])
        result=self.client.get("/api/v1/herbs",params={"family":detail["family"],"genus":detail["genus"],
            "region":region,"part":"根茎"}).json()
        self.assertIn("tcmp-004",[h["id"] for h in result["items"]])
        self.assertTrue(all(h["family"]==detail["family"] and h["genus"]==detail["genus"]
            and region in h["distribution"] and "根茎" in h["medicinalPart"] for h in result["items"]))
        self.assertEqual(self.client.get("/api/v1/herbs",params={"q":"nonexistent-plant-987"}).json()["total"],0)

    def test_detail_preserves_source_and_uncertainty(self):
        for herb_id,row in catalog.rows().items():
            response=self.client.get("/api/v1/herbs/"+herb_id)
            self.assertEqual(response.status_code,200)
            detail=response.json()
            self.assertEqual(detail["distribution"],row["活体植物分布地区"])
            self.assertEqual(detail["toxicity"],row["毒性"])
            self.assertEqual(detail["materials"],json.loads(row["药材记录JSON"] or "[]"))
            self.assertEqual(detail["reviewStatus"],row["人工审核状态"])
            self.assertEqual(detail["sources"],catalog.serialize(row,True)["sources"])
        conflict=self.client.get("/api/v1/herbs/tcmp-051").json()
        self.assertTrue(conflict["identityConflict"])
        self.assertEqual(conflict["acceptedLatinName"],"")
        self.assertEqual(conflict["latinName"],catalog.rows()["tcmp-051"]["Latin Name"])
        fern=self.client.get("/api/v1/herbs/tcmp-175").json()
        self.assertEqual(fern["sporeSeason"],catalog.rows()["tcmp-175"]["孢子期"])
        self.assertEqual(fern["flowering"],catalog.rows()["tcmp-175"]["花期"])

    def test_effect_terms_work_in_keyword_search(self):
        search=self.client.get("/api/v1/herbs",params={"q":"清热解毒","page_size":60}).json()
        filtered=self.client.get("/api/v1/herbs",params={"effect":"清热解毒","page_size":60}).json()
        expected=[herb_id for herb_id,row in catalog.rows().items() if "清热解毒" in row["传统功效"]]
        self.assertEqual([herb["id"] for herb in search["items"]],expected)
        self.assertEqual(search["total"],filtered["total"])
        self.assertGreater(search["total"],0)
        self.assertEqual(search["collectionTotal"],300)

    def test_reference_image_and_path_boundary(self):
        path=catalog.reference_image("tcmp-004")
        self.assertTrue(path.is_relative_to(catalog.TRAIN_IMAGES.resolve()))
        image=self.client.get("/api/v1/herbs/tcmp-004/reference-image")
        self.assertEqual(image.status_code,200)
        self.assertEqual(hashlib.sha256(image.content).digest(),hashlib.sha256(path.read_bytes()).digest())
        for candidate in ("../../api.py",str(catalog.ROOT/"api.py")):
            with patch.object(catalog,"rows",return_value={"unsafe":{"封面图候选":candidate}}):
                self.assertIsNone(catalog.reference_image("unsafe"))
        self.assertEqual(self.client.get("/api/v1/herbs/unknown/reference-image").status_code,404)

    def test_validation_filters_and_recent_order(self):
        self.assertEqual(self.client.get("/api/v1/herbs/unknown").status_code,404)
        for params in ({"page":0},{"page_size":0},{"page_size":61}):
            self.assertEqual(self.client.get("/api/v1/herbs",params=params).status_code,422)
        data=self.client.get("/api/v1/herbs/filters").json()
        self.assertEqual(data["total"],300)
        self.assertEqual(data["distributionCount"],299)
        self.assertEqual(data["parts"],sorted(set(data["parts"])))
        self.assertTrue(set(data["parts"]).issubset(set(catalog.PARTS)))
        self.assertEqual(catalog.serialize(catalog.rows()["tcmp-003"])["medicinalPart"],["根","叶","花"])
        self.assertFalse(catalog.region_matches(catalog.rows()["tcmp-019"]["活体植物分布地区"],"新疆"))
        self.assertFalse(catalog.region_matches(catalog.rows()["tcmp-004"]["活体植物分布地区"],"海南"))
        self.assertTrue(catalog.region_matches(catalog.rows()["tcmp-004"]["活体植物分布地区"],"广东"))
        result=self.client.get("/api/v1/herbs",params={"sort":"recent","recent_ids":"tcmp-300,tcmp-004"}).json()
        self.assertEqual([h["id"] for h in result["items"][:2]],["tcmp-300","tcmp-004"])


if __name__=="__main__":
    unittest.main(verbosity=2)
