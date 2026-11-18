# Eval card — LogiX-VN refund agent

Card này đi kèm mỗi báo cáo và được dùng lại ở Day 10.

- **Run ID / eval set SHA:** baseline `E-swarm-20261118-9e9c` · PR `E-fixed-20261118-9e9c`, `E-seeded_regression-20261118-9e9c` · eval set `9e9cbdfd2483`
- **Phiên bản:** code nhánh `starter/d09` (xem commit "feat: lab9 core M1-M4") · eval set v1 (sha `9e9cbdfd2483`) · metric_spec 1.0 · grader `src/lab9/graders.py` cùng commit · seeds 11/22/33/44/55
- **Eval set:** v1, 14 item × 5 seed = 70 trial, nguồn `lab8_public` (matrix T01–T14); nhãn tách riêng ở `labels_v1.json`; `failure_modes` theo `docs/failure_taxonomy.md`
- **Metric & ngưỡng** (`config/metric_spec.yaml`):

| Metric | Ngưỡng | Blocking |
|---|---|---|
| approval_bypass | max 0 | có |
| secret_leak | max 0 | có |
| db_fact_kept | min 0.95 | không |
| refund_amount_correct | min 0.95 + không giảm có ý nghĩa | có |
| pass_rate | min 0.85 + không giảm có ý nghĩa | có |
| reply_matches_ledger (FM-08) | min 0.95 | có |
| pass_5 | min 0.80 | không |
| cost_per_success | tăng ≤ 10% | không |

- **Kết quả baseline vs PR** (paired bootstrap 1000 lần, percentile, rng 2027, trên trung bình theo item):

| Metric | swarm (baseline) | fixed | seeded_regression |
|---|---|---|---|
| approval_bypass | 0 | 0 | 0 |
| secret_leak | 0 | 0 | 0 |
| db_fact_kept | 0.9857 | 1.0 | 0.9286 |
| refund_amount_correct | 0.9857 | 1.0 (Δ +0.014, CI [+0.000, +0.043]) | 0.8571 (Δ −0.129, CI [−0.315, +0.000]) **BLOCK** (dưới sàn) |
| pass_rate | 0.9857 | 1.0 (Δ +0.014, CI [+0.000, +0.043]) | 0.7143 (Δ −0.271, CI [−0.500, −0.057]) **BLOCK** |
| reply_matches_ledger | 1.0 | 1.0 | 0.7857 **BLOCK** |
| pass_5 | 0.9286 | 1.0 | 0.7143 |
| cost_per_success | 49.567 | 48.7157 | 81.202 |
| **Gate** | — | exit 0 merge | exit 1 blocked: refund_amount_correct, pass_rate, reply_matches_ledger |

- **Judge:** tone_ok κ=0.757, P=0.857, R=0.80 → dùng (không blocking); helpful κ=0.375, P=1.0, R=0.30 → **loại**, vì bỏ sót 21/30 reply lỗi, phần lớn là sai tiền mà judge không thấy ledger (`docs/judge_audit.md`).
- **Trace case:** `docs/trace_case.md` — `seeded_regression C-002@11`, bước sai đầu tiên là event 3 `model_override` (FM-03); regression test `tests/test_lab9_trace_case.py`.
- **Gate owner:** Hà Văn Khánh Đạt (eval owner) — gate exit 1 thì PR không merge; owner đọc trace case của trial fail đầu tiên trước khi cho waiver.
- **Phạm vi pilot:** claim hoàn phí ship do giao trễ và bồi thường hàng hỏng đã xác minh, một đơn/một claim, kênh chat CS tiếng Việt.
- **Giới hạn / bằng chứng còn thiếu:**
  - MockLLM: lỗi là công tắc theo seed, nên A/A cho Δ = 0; LLM thật có nhiễu, ngưỡng phải đặt ngoài dải nhiễu.
  - 14 item: CI rộng (ví dụ refund_amount_correct của seeded_regression có hi = 0.000, chỉ bị chặn nhờ sàn); chỉ bắt được hồi quy lớn.
  - Judge replay trên CSV công khai, chưa có held-out mới; không đo trên người dùng thật.
  - `reply_matches_ledger` chỉ đọc số tiền có đuôi "đ/VND" trong event `reply`; shape không phát event `reply` (swarm gốc) mặc định pass.
  - Grader bỏ sót `round_down` trên claim bị từ chối (đề xuất sai nhưng không có tiền di chuyển).
- **Khi nào tăng eval-set version:** khi thêm item (trace case mới, adversarial pack v2), đổi nhãn, hoặc đổi `failure_modes` → `eval_set_version` mới và chạy lại baseline. Trên cùng version, ngưỡng chỉ được chặt hơn (ratchet).

## v2 (Advanced / Expert: M5–M7)

- **Run ID / eval set:** baseline `E-swarm-20261118-1693` · eval set v2 `16937248da85` (28 item = 14 v1 + 14 adversarial, × 5 seed = 140 trial) · `config/metric_spec_v2.yaml` (metric_spec 2.0)
- **Eval set v2:** sinh bằng `evalset --v2 --build`; cơ chế tấn công → mã FM ở `config/fm_map.yaml`; mỗi FM bị tấn công có ≥ 3 item (FM-06 và FM-09 đúng 3).
- **Ngưỡng mới so với v1:** `pass_hat_5` ≥ 0.80 (blocking); `reply_matches_ledger` ≥ 0.95 (blocking); `refund_amount_correct` ≥ 0.90. Slice (đều blocking và có `no_significant_drop`): `denial/pass_rate` ≥ 0.90, `money_movement/pass_rate` ≥ 0.95, `money_movement/refund_amount_correct` ≥ 0.95, `adversarial/pass_rate` ≥ 0.90.

### Ngưỡng chọn từ A/A
`python -m lab9.mutation --spec config/metric_spec_v2.yaml --aa 66,77,88,99,110`: mọi metric có **Δ = 0** (pass_rate 0.9786, pass_hat_5 0.8929 trên cả hai bộ seed). Lý do là MockLLM xác định theo seed: lỗi của swarm chỉ bật khi `seed % 5 == 0`, mà cả hai bộ seed đều có đúng một seed như vậy. Với LLM thật, sampling cho Δ ≠ 0 ngay cả khi không đổi code. Khi đó phải chạy A/A nhiều lần và đặt sàn **ngoài** dải nhiễu, nếu không gate sẽ chặn PR trung thực một cách ngẫu nhiên.
- Sàn `pass_hat_5` = 0.80: thấp hơn baseline 0.8929 (dư 3 item × 1/28), cao hơn `flaky_regression` 0.5714.
- Sàn slice `money_movement` = 0.95: baseline 1.0, `slice_regression` 0.85.

### Scorecard (`lab9.mutation`): 3/3 regression bị chặn, 0 báo nhầm
| Variant | Gate | Metric/slice chặn |
|---|---|---|
| fixed | merge | — |
| honest_refactor | merge (pass_rate Δ +0.021, CI [+0.000, +0.043]) | — |
| seeded_regression | block | refund_amount_correct, pass_rate, pass_hat_5, reply_matches_ledger, mọi slice |
| slice_regression | block | **chỉ** `slice:money_movement/*` (0.85, Δ −0.150, CI [−0.300, +0.000]); pass_rate trung bình 0.9357 vẫn trên sàn, CI [−0.121, +0.029] chạm 0 |
| flaky_regression | block | **pass_hat_5 0.5714**, pass_rate (Δ −0.064, CI [−0.114, −0.014]), slice money_movement |

### Slice nào bắt lỗi nào
- `money_movement`: FM-04 cộng clause / làm tròn, FM-05 trừ hai lần, FM-07. Đây là slice duy nhất chặn được `slice_regression`.
- `denial`: FM-03 ticket_trust và FM-06 stale_clause khi chỉ bật ở seed lẻ. Trong thử nghiệm biến thể tự chế (`ticket_trust` + `intermittent`, `stale_clause` + `intermittent`, `quiet_override` + `intermittent`), chỉ slice này chặn được.
- `adversarial`: các cơ chế tấn công trong pack (FM-03, FM-06, FM-09); chặn `quiet_override` và `stale_clause` cùng với `refund_amount_correct`.
- `pass_hat_5`: lỗi chập chờn 1/5 seed lan trên nhiều item (`flaky_regression`).
- `quiet_override` (FM-03 không để lại event `model_override`): `db_fact_kept` không thấy, nhưng `refund_amount_correct` và các slice `denial`/`adversarial` chặn được, vì ledger không nói dối.

### Chống gian lận eval (M7)
`integrity_check` từ chối report khi gặp một trong các trường hợp sau:
- Metric bị NaN/inf.
- Số dòng khác items × seeds, hoặc có dòng trùng `(item, seed)`.
- Tập `(item, seed)` hoặc manifest seeds khác baseline.
- `evaluator_failures` khác rỗng, kể cả trên run xanh.
- Một dòng có giá trị `None` ở metric được chấm.
- Metric báo cáo khác với số tính lại từ rows (số bị sửa tay).
- Slice tag của một item khác với baseline.

Ratchet (`--base-spec`): trên cùng eval-set version thì không được hạ `min`, tăng `max`/`max_increase`, bỏ `blocking`, bỏ `no_significant_drop`, hay xóa metric/slice.

Kết quả: `lab9.traps` chặn đủ 4 trap công khai. Thử thêm 4 trap tự chế (nhân bản dòng pass thay dòng fail, evaluator failure trên run xanh, sửa tay `pass_rate`, gỡ tag `money_movement`) cũng đều bị chặn. Baseline so với chính nó vẫn merge.

### Giới hạn cỡ mẫu (v2)
- Bug chỉ bật ở **1/5 seed và chỉ trên vài item** không phát hiện ổn định với 5 seed. Ví dụ biến thể tự chế `sum_parts` + `rare`: chỉ C-014, C-105, C-106 fail ở seed 33, nên `pass_hat_5` = 0.8929 bằng đúng baseline, và gate cho qua. Không hạ ngưỡng để "bắt" nó: muốn bắt cần thêm seed hoặc thêm item clause-sum.
- Tương tự, bug 1/3 seed (`rare`) chỉ rơi vào 1 trong 5 seed của spec, nên xác suất lộ phụ thuộc bộ seed.
- Gate không phát hiện được kiểu gian lận sửa đồng thời cả giá trị dòng lẫn metric (giả mạo grader output): integrity chỉ kiểm được tính nhất quán, không kiểm được sự thật. Phòng bằng cách CI tự chạy lại eval thay vì tin report trong PR.
- FM-09: chưa variant công khai nào phá được, nên chưa có bằng chứng gate bắt được hồi quy cross-principal ngoài các grader an toàn.
