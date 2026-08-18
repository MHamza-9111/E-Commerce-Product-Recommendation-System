(function () {
    "use strict";

    document.documentElement.classList.add("js");

    function ready(callback) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", callback);
        } else {
            callback();
        }
    }

    ready(function () {
        var header = document.querySelector(".site-header");
        var backButton = document.getElementById("back-to-top");

        function updateScrollState() {
            var hasScrolled = window.scrollY > 16;
            if (header) header.classList.toggle("is-scrolled", hasScrolled);
            if (backButton) backButton.classList.toggle("show", window.scrollY > 360);
        }

        updateScrollState();
        window.addEventListener("scroll", updateScrollState, { passive: true });

        if (backButton) {
            backButton.addEventListener("click", function () {
                window.scrollTo({ top: 0, behavior: "smooth" });
            });
        }

        // Reveal content only when it reaches the viewport. Content remains visible
        // for users who disable JavaScript or request reduced motion.
        var revealElements = document.querySelectorAll("[data-reveal]");
        if ("IntersectionObserver" in window) {
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        entry.target.classList.add("is-visible");
                        observer.unobserve(entry.target);
                    }
                });
            }, { threshold: 0.08, rootMargin: "0px 0px -24px" });

            revealElements.forEach(function (element) {
                observer.observe(element);
            });
        } else {
            revealElements.forEach(function (element) {
                element.classList.add("is-visible");
            });
        }

        // Product review helper.
        document.querySelectorAll("[data-review-rating]").forEach(function (input) {
            input.addEventListener("change", function () {
                var ratingText = document.querySelector("[data-rating-text]");
                if (ratingText) ratingText.textContent = input.value + " out of 5";
            });
        });

        // Accessible password show/hide controls.
        document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
            button.addEventListener("click", function () {
                var targetId = button.getAttribute("data-password-toggle");
                var input = document.getElementById(targetId);
                if (!input) return;

                var isPassword = input.type === "password";
                input.type = isPassword ? "text" : "password";
                button.textContent = isPassword ? "Hide" : "Show";
                button.setAttribute("aria-label", (isPassword ? "Hide" : "Show") + " password");
            });
        });

        // Briefly show submit progress without interfering with browser validation.
        document.querySelectorAll("form[data-submit-label]").forEach(function (form) {
            form.addEventListener("submit", function () {
                if (!form.checkValidity()) return;
                var submitButton = form.querySelector('[type="submit"]');
                if (!submitButton) return;
                submitButton.disabled = true;
                submitButton.textContent = form.getAttribute("data-submit-label") || "Please wait…";
            });
        });

        // Smoothly dismiss flash messages while keeping the manual close button.
        var flashContainer = document.getElementById("flashContainer");
        if (flashContainer) {
            window.setTimeout(function () {
                flashContainer.style.opacity = "0";
                flashContainer.style.transform = "translateY(-8px)";
                window.setTimeout(function () { flashContainer.remove(); }, 250);
            }, 5500);
        }
    });
})();
