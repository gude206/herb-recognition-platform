# Fixed-checkpoint paired test comparison

All differences are evaluation B minus evaluation A.

| Metric | A | B | Difference (pp) | Paired bootstrap 95% CI (pp) | Exact McNemar p |
|---|---:|---:|---:|---:|---:|
| top1 | 79.85% | 80.00% | +0.148 | [-0.845, +1.162] | 0.8034 |
| top5 | 92.29% | 92.82% | +0.528 | [-0.148, +1.204] | 0.1492 |

Top-1 discordant pairs: only A correct = 287; only B correct = 294.

The Top-1 interval includes zero; this comparison does not establish a Top-1 difference.

Images are resampled as independent units. Correlated source images require a source-group analysis. This comparison does not measure variability across training seeds and must not be used to retune on the test set.

Evaluation A: D:\Study\AI全栈开发\TCMP-300\runs\resnet50_7030_baseline\paired_test_evaluation
Evaluation B: D:\Study\AI全栈开发\TCMP-300\runs\resnet50_7030_ZQ\paired_test_evaluation
Test images: 4735; bootstrap replicates: 10000; seed: 20261001.
Inference settings: {"autocast_float16": true, "batch_size": 16, "device": "cuda", "preprocessing": "Resize256_CenterCrop224_RGB_ImageNetNormalize_v1", "workers": 2}
Dataset fingerprint: 02eb52aeebfc35dcc547bf13c4e74a26e903a389de74fdaef5d638f74ff4d1aa
Split hash: a54b9f2faa7b68053ebaba873a184ef171eaf58407672ab3d464df432b593f09
