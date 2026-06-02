function get_review_preview_data() {
    return {
        user_name: document.getElementById("preview_user_name").value,
        product_name: document.getElementById("preview_product_name").value,
        rating: document.getElementById("preview_rating").value,
        comment: document.getElementById("preview_comment").value
    };
}

async function update_preview() {
    const response = await fetch("/api/review-preview", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(get_review_preview_data())
    });

    const data = await response.json();
    document.getElementById("preview_result").innerHTML = data.html;
}

document.getElementById("preview_button").addEventListener("click", update_preview);
