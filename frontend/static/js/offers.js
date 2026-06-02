const params = new URLSearchParams(window.location.search);
const coupon = params.get("coupon");

if (coupon) {
    const target = document.getElementById("coupon-message");
    target.textContent = coupon;
}
