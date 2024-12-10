document.addEventListener("DOMContentLoaded", function() {
    const form = document.getElementById("send-email-form");
    form.addEventListener("submit", function(event) {
        event.preventDefault();
        const toEmail = document.getElementById("to_email").value;
        const subject = document.getElementById("subject").value;
        const body = document.getElementById("body").value;

        fetch("/email", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ to_email: toEmail, subject: subject, body: body })
        }).then(response => response.json()).then(data => {
            if (data.success) {
                alert("Email sent successfully!");
                form.reset();
            } else {
                alert("Failed to send email.");
            }
        });
    });
});
