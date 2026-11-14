import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent/'experiment5/data'

class DataTests(unittest.TestCase):
    def test_species_and_text_do_not_cross_splits(self):
        groups=[json.loads((ROOT/name).read_text(encoding='utf-8')) for name in ['agent_finetune_data.json','agent_validation_data.json','agent_test_data.json']]
        self.assertEqual([len(g) for g in groups],[100,10,10])
        for i,j in [(0,1),(0,2),(1,2)]:
            self.assertFalse({x['plant_id'] for x in groups[i]}&{x['plant_id'] for x in groups[j]})
            self.assertFalse({x['input'] for x in groups[i]}&{x['input'] for x in groups[j]})
        self.assertTrue(all(x['sources'] and x['input'].strip() and x['output'] for group in groups for x in group))
    def test_manifest_discloses_field_labels_and_unrepresented_classes(self):
        manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('weak',manifest['label_status'])
        self.assertEqual(manifest['missing_training_classes'],['本草文化','其他'])
