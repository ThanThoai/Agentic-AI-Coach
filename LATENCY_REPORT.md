# Báo cáo Latency theo mức Input Token (vLLM)

Mỗi bảng: một model, các dòng là mức token tăng dần. Cột tách bạch **prefill**, **ttft**, **decode**, **tốc độ decode**, và **full latency** (total_ms). Giá trị là trung bình trên các kịch bản × lần lặp.

## llama_guard_3_1b (1.0B) — ~3.77 ký tự VN/token

| token (target→~thực) | ~ký tự VN | prefill_ms | ttft_ms | decode_ms | ms/token decode | **full latency** | full p95 |
|---|---|---|---|---|---|---|---|
| 50 → 246 | ~927 | 6.94 | 6.94 | 13.59 | 4.53 | **20.52** | 29.47 |
| 150 → 246 | ~927 | 6.92 | 6.92 | 13.57 | 4.53 | **20.49** | 29.43 |
| 400 → 389 | ~1,466 | 8.17 | 8.17 | 12.94 | 4.54 | **21.10** | 30.79 |
| 1000 → 1002 | ~3,777 | 14.33 | 14.33 | 13.02 | 4.55 | **27.35** | 37.24 |
| 2500 → 2488 | ~9,379 | 35.00 | 35.00 | 13.76 | 4.83 | **48.77** | 58.86 |
| 6000 → 5992 | ~22,589 | 86.86 | 86.86 | 15.47 | 5.81 | **102.33** | 113.61 |

## shieldgemma_2b (2.0B) — ~3.83 ký tự VN/token

| token (target→~thực) | ~ký tự VN | prefill_ms | ttft_ms | decode_ms | ms/token decode | **full latency** | full p95 |
|---|---|---|---|---|---|---|---|
| 50 → 159 | ~608 | 12.39 | 12.39 | 0.00 | 0.00 | **12.39** | 12.76 |
| 150 → 159 | ~608 | 12.15 | 12.15 | 0.00 | 0.00 | **12.15** | 12.32 |
| 400 → 373 | ~1,428 | 14.15 | 14.15 | 0.00 | 0.00 | **14.15** | 14.34 |
| 1000 → 1007 | ~3,856 | 29.26 | 29.26 | 0.00 | 0.00 | **29.26** | 29.98 |
| 2500 → 2487 | ~9,525 | 66.84 | 66.84 | 0.00 | 0.00 | **66.84** | 68.13 |
| 6000 → 5981 | ~22,907 | 163.92 | 163.92 | 0.00 | 0.00 | **163.92** | 167.05 |

## qwen3guard_4b (4.0B) — ~3.58 ký tự VN/token

| token (target→~thực) | ~ký tự VN | prefill_ms | ttft_ms | decode_ms | ms/token decode | **full latency** | full p95 |
|---|---|---|---|---|---|---|---|
| 50 → 368 | ~1,317 | 22.13 | 22.13 | 138.51 | 12.82 | **160.64** | 204.67 |
| 150 → 368 | ~1,317 | 22.11 | 22.11 | 138.49 | 12.82 | **160.60** | 205.11 |
| 400 → 425 | ~1,521 | 24.72 | 24.72 | 136.24 | 12.85 | **160.96** | 205.20 |
| 1000 → 997 | ~3,569 | 44.86 | 44.86 | 142.16 | 13.26 | **187.02** | 230.08 |
| 2500 → 2504 | ~8,964 | 110.50 | 110.50 | 147.21 | 13.74 | **257.70** | 301.84 |
| 6000 → 5995 | ~21,462 | 300.94 | 300.94 | 153.94 | 14.38 | **454.87** | 506.02 |

## granite_guardian_8b (8.0B) — ~1.84 ký tự VN/token

| token (target→~thực) | ~ký tự VN | prefill_ms | ttft_ms | decode_ms | ms/token decode | **full latency** | full p95 |
|---|---|---|---|---|---|---|---|
| 50 → 207 | ~380 | 33.39 | 33.39 | 358.44 | 23.90 | **391.82** | 398.68 |
| 150 → 207 | ~380 | 33.40 | 33.40 | 358.42 | 23.89 | **391.82** | 398.48 |
| 400 → 413 | ~759 | 41.23 | 41.23 | 363.29 | 24.22 | **404.52** | 409.01 |
| 1000 → 1017 | ~1,871 | 88.12 | 88.12 | 367.56 | 24.50 | **455.69** | 467.61 |
| 2500 → 2516 | ~4,629 | 222.94 | 222.94 | 372.82 | 24.86 | **595.76** | 607.67 |
| 6000 → 6004 | ~11,047 | 587.08 | 587.08 | 406.31 | 27.09 | **993.38** | 1021.71 |

## shieldgemma_9b (9.0B) — ~3.83 ký tự VN/token

| token (target→~thực) | ~ký tự VN | prefill_ms | ttft_ms | decode_ms | ms/token decode | **full latency** | full p95 |
|---|---|---|---|---|---|---|---|
| 50 → 159 | ~608 | 34.84 | 34.84 | 0.00 | 0.00 | **34.84** | 35.46 |
| 150 → 159 | ~608 | 34.78 | 34.78 | 0.00 | 0.00 | **34.78** | 35.60 |
| 400 → 373 | ~1,428 | 44.64 | 44.64 | 0.00 | 0.00 | **44.64** | 45.59 |
| 1000 → 1007 | ~3,856 | 101.88 | 101.88 | 0.00 | 0.00 | **101.88** | 104.93 |
| 2500 → 2487 | ~9,525 | 242.68 | 242.68 | 0.00 | 0.00 | **242.68** | 249.69 |
| 6000 → 5981 | ~22,907 | 639.38 | 639.38 | 0.00 | 0.00 | **639.38** | 655.25 |

## Cách đọc

- **prefill_ms ≈ ttft_ms**: chi phí xử lý input; tăng ~tuyến tính theo token.
- **decode_ms**: gần như **không đổi** theo input token (chỉ phụ thuộc độ dài verdict). Classifier (ShieldGemma) = 0.
- **full latency (total_ms)** = ttft + decode. Với model sinh verdict dài (Granite), decode chiếm phần lớn full latency.

Hình: `plots/breakdown_<model>.png` (cột chồng prefill+decode), `plots/lines_<model>.png` (đường theo token), `plots/fulllatency_all.png` (so sánh full latency).

## Quy đổi token ↔ độ dài văn bản tiếng Việt

Đo thực trên văn bản tiếng Việt tự nhiên bằng chính tokenizer từng model. Quy tắc ngón tay cái (đa số model Llama/Qwen/Gemma): **1 token ≈ 3,7 ký tự ≈ 0,8 âm tiết**, tức 1 âm tiết ≈ 1,2 token.

| Tokenizer | ký tự VN/token | 6000 token ≈ | ~số trang A4 |
|---|---|---|---|
| Llama Guard 3 | 3,77 | ~22.600 ký tự · ~4.900 âm tiết | ~8–10 trang |
| Qwen3Guard | 3,58 | ~21.500 ký tự · ~4.700 âm tiết | ~8–10 trang |
| ShieldGemma | 3,83 | ~23.000 ký tự · ~5.000 âm tiết | ~8–10 trang |
| **Granite 3.3** | **1,84** | **~11.000 ký tự · ~2.400 âm tiết** | **~4–5 trang** |

**Lưu ý:** benchmark độn token bằng tokenizer của TỪNG model nên mỗi mức token là token thật của model đó — chuẩn để đo *latency/token*. Nhưng tokenizer Granite cắt vụn tiếng Việt ~2× nên cùng '6000 token' chỉ chứa ~một nửa lượng chữ so với Llama/Qwen. Khi so sánh latency cho *cùng một tài liệu tiếng Việt*, Granite sẽ sinh ~2× token → latency thực tế còn cao hơn bảng '@token' thể hiện. Cột `~ký tự VN` trong mỗi bảng trên đã quy đổi sẵn.
