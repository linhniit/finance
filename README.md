# Vàng & Tỷ giá

Website tiếng Việt dành cho **linhniit**. Chạy trực tiếp trên GitHub Pages, không cần máy chủ hoặc API key.

- Giá mua/bán vàng Mi Hồng: SJC và 999.
- Giá vàng quốc tế và tỷ giá USD/VND từ Markets Insider.
- Các khoảng: 1 ngày, 1 tuần, 1 tháng, 3 tháng, 6 tháng, 1 năm.
- Tooltip, phím mũi tên để xem từng mốc, bảng dữ liệu và bố cục điện thoại.
- GitHub Actions lấy dữ liệu mỗi ngày vào khoảng **18:37 giờ Việt Nam** (`37 11 * * *` UTC), lưu lịch sử vào Git và xuất bản lại website.

## Dữ liệu và ý nghĩa biểu đồ

Nguồn gốc:

- https://mihong.com/gia-vang-trong-nuoc
- https://markets.businessinsider.com/commodities/gold-price
- https://markets.businessinsider.com/currencies/usd-vnd

Liên kết USD/VND đã được sửa từ liên kết giá vàng trùng trong yêu cầu sang trang cặp tiền của cùng nhà cung cấp.

Mi Hồng: dùng API công khai mà trang nguồn sử dụng, `/v1/gold-prices`, với `market=domestic`, `goldCode=SJC|999`, `last=24h|1M|1y`. Dữ liệu `1M` là các mốc tổng hợp theo ngày; `1y` là các mốc tổng hợp theo tháng, không được giả định là giá đóng cửa. Mốc tháng chỉ bổ sung phần lịch sử trước mốc ngày sớm nhất. Biểu đồ và tooltip ghi rõ loại bản ghi. Đơn vị gốc VND/chỉ được giữ nguyên (1 lượng = 10 chỉ).

Markets Insider: đọc JSON nhúng `priceSection`, `historicalPrices` và đường dẫn lịch sử công khai do giao diện nguồn sử dụng. Lịch sử dùng `Close`. Giá mới nhất được ghi với thời điểm **thu thập** theo giờ Việt Nam, không giả định đó là thời điểm giao dịch. Ngày đóng cửa được giữ theo ngày do nguồn trả về. Một bản ghi thu thập có thể không nằm cùng ngày giao dịch với giá đóng cửa do khác múi giờ.

Mục 1 ngày của Mi Hồng dùng các mốc trong ngày gần nhất do nguồn cung cấp; vàng quốc tế và USD/VND có một mốc thu thập/ngày. Không tạo dữ liệu theo giờ, không nội suy hoặc bịa dữ liệu lịch sử. Ngày thiếu dữ liệu không được điền bằng số 0. Lịch sử dài hạn sẽ ngày càng có nhiều mốc ngày nhờ lịch cập nhật.

Nguồn có thể thay đổi cấu trúc hoặc từ chối yêu cầu. Khi lỗi, dữ liệu thành công gần nhất được giữ lại, trạng thái lỗi được hiển thị và workflow báo thất bại **sau khi xuất bản dữ liệu còn lại**. Không có CAPTCHA hoặc cơ chế kiểm soát truy cập nào được vượt qua.

## Repository và website

- Mã nguồn: https://github.com/linhniit/finance
- Website: https://linhniit.github.io/finance/
- Nhánh xuất bản: `main`.
- Workflow: `.github/workflows/update-and-deploy.yml`.

Trong **Settings → Pages**, chọn nguồn **GitHub Actions**. Mỗi lần thay đổi website trên `main`, workflow kiểm tra dữ liệu, cập nhật giá và xuất bản. Để cập nhật thủ công: **Actions → Cập nhật giá và xuất bản website → Run workflow**.

Workflow cần quyền ghi nội dung để lưu lịch sử, và quyền Pages/OIDC để xuất bản. Không cần API key hoặc lưu token thủ công vào mã nguồn. Chỉ các tài nguyên giao diện và `data/market.json` được đưa vào artifact Pages.

GitHub có thể trì hoãn lịch chạy; schedule chỉ hoạt động trên nhánh mặc định. GitHub có thể tắt schedule trên repository public không có hoạt động trong 60 ngày; kiểm tra Actions nếu trang báo dữ liệu quá 36 giờ. Hướng dẫn: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

## Xem và cập nhật tại máy

Yêu cầu Python 3.10+ (có dữ liệu múi giờ hệ thống).

```sh
python3 scripts/update_data.py
python3 -m http.server 4173
```

Mở http://localhost:4173/. Không mở HTML bằng `file://` vì trình duyệt cần HTTP để tải JSON.

```sh
python3 -m unittest discover -s tests -v
node --check app.js
```

Website dùng HTML/CSS/JavaScript thuần và SVG. Không tải thư viện từ CDN. Thư mục `_site/` chỉ chứa tài nguyên website khi xuất bản; script, tests và workflow không được đưa vào artifact Pages.
