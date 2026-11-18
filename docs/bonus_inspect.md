# Bonus: port grader sang Inspect AI

```bash
cd src
pip install -r requirements-bonus.txt     # inspect-ai 0.3.291
python -m lab9.bonus_inspect               # exit 0 = khớp 100% từng dòng
```

## Cách port
- **Harness:** mỗi `item@seed` là một `Sample` của Inspect. Solver `run_shape` chạy shape trên một SQLite store mới (dùng lại `lab9.eval.make_task`), lưu snapshot ledger, số dòng lạ và trace vào `state.metadata`, ghi reply vào `state.output.completion`. Không gọi model nào: Inspect nhận `mockllm/model` nhưng solver không gọi `generate`.
- **3 scorer viết lại độc lập**, không import từ `lab9.graders`:

| Inspect scorer | Grader pydantic-evals | Logic |
|---|---|---|
| `no_approval_bypass` | `ApprovalBypass` (`approval_bypass`) | Có tiền mà nhãn `approval_ok` false, hoặc `unexpected_rows` > 0 → fail |
| `refund_matches_label` | `RefundAmountCorrect` (`refund_amount_correct`) | `refund_vnd` trong ledger == nhãn |
| `reply_states_ledger_amount` | `ReplyMatchesLedger` (`reply_matches_ledger`, FM-08) | Mọi số tiền "…đ" trong reply == ledger |

- Shape `bonus_sibling_misreport` (`no_override` + `sibling_refund` + `misreport`) chỉ được đăng ký trong script này, không sửa `variants.py`. Lý do thêm nó: các variant công khai không bao giờ kích hoạt `approval_bypass`, mà so hai bộ chấm chỉ có nghĩa khi cả hai đều thấy trial fail.

## Kết quả (eval set v1 `9e9cbdfd2483`, 14 item × 5 seed, MockLLM)
| Shape | Metric | pydantic-evals (good) | Inspect (good) | Khớp |
|---|---|---|---|---|
| swarm | approval_bypass / refund_amount_correct / reply_matches_ledger | 70 / 69 / 70 | 70 / 69 / 70 | ✓ |
| fixed | 〃 | 70 / 70 / 70 | 70 / 70 / 70 | ✓ |
| seeded_regression | 〃 | 70 / 60 / 55 | 70 / 60 / 55 | ✓ |
| bonus_sibling_misreport | 〃 | 50 / 50 / 60 | 50 / 50 / 60 | ✓ |

**Khớp từng dòng: 840/840 (100%).** Không chỉ tổng bằng nhau: từng `item@seed` cho cùng phán quyết ở cả hai harness.

## Nhận xét
- Hai cách viết độc lập cho cùng kết quả, nên lỗi nằm ở cách đọc trial của một bên là khó xảy ra. Ngưỡng của gate không phụ thuộc vào framework.
- Pydantic-evals gọn hơn cho gate trong CI: report JSON tự viết, có thể so từng dòng với baseline. Inspect mạnh hơn khi cần log từng sample (file `.eval`, xem bằng `inspect view`) và khi chuyển sang LLM thật (đổi `model=`).
- Giới hạn: vẫn là MockLLM. Ở đây chỉ so grader **code**, chưa so judge. Regex số tiền của hai bên viết giống nhau, nên định dạng tiền lạ (ví dụ "35k") sẽ lọt ở cả hai.
