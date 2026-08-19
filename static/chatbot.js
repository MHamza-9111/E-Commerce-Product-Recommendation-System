(function () {
    "use strict";

    const chatbot = document.getElementById("apbot");
    if (!chatbot) return;

    const urls = {
        api: chatbot.dataset.apiUrl,
        products: chatbot.dataset.productsUrl,
        sale: chatbot.dataset.saleUrl,
        orders: chatbot.dataset.ordersUrl,
        cart: chatbot.dataset.cartUrl,
        checkout: chatbot.dataset.checkoutUrl,
        profile: chatbot.dataset.profileUrl
    };

    const toggleButton = document.getElementById("apbotToggle");
    const closeButton = document.getElementById("apbotClose");
    const chatWindow = document.getElementById("apbotWindow");
    const dragHandle = document.getElementById("apbotDragHandle");
    const messages = document.getElementById("apbotMessages");
    const form = document.getElementById("apbotForm");
    const input = document.getElementById("apbotInput");
    const sendButton = document.getElementById("apbotSend");
    const quickButtons = document.querySelectorAll("[data-apbot-message]");
    const nudge = document.getElementById("apbotNudge");
    const nudgeOpen = document.getElementById("apbotNudgeOpen");
    const nudgeClose = document.getElementById("apbotNudgeClose");
    const positionKey = "zilocart-apbot-position";
    let dragState = null;

    function desktopDragEnabled() {
        return window.matchMedia("(min-width: 576px)").matches;
    }

    function keepInsideViewport(left, top) {
        const gap = 10;
        const maxLeft = Math.max(gap, window.innerWidth - chatWindow.offsetWidth - gap);
        const maxTop = Math.max(gap, window.innerHeight - chatWindow.offsetHeight - gap);
        return {
            left: Math.min(Math.max(gap, left), maxLeft),
            top: Math.min(Math.max(gap, top), maxTop)
        };
    }

    function placeWindow(left, top, savePosition) {
        if (!desktopDragEnabled()) return;
        const safe = keepInsideViewport(left, top);
        chatWindow.classList.add("apbot-positioned");
        chatWindow.style.left = safe.left + "px";
        chatWindow.style.top = safe.top + "px";
        if (savePosition) {
            try { localStorage.setItem(positionKey, JSON.stringify(safe)); } catch (error) { /* Storage is optional. */ }
        }
    }

    function restoreWindowPosition() {
        if (!desktopDragEnabled()) return;
        try {
            const saved = JSON.parse(localStorage.getItem(positionKey));
            if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
                placeWindow(saved.left, saved.top, false);
            }
        } catch (error) { /* Use the default position when storage is unavailable. */ }
    }

    function resetWindowPosition() {
        chatWindow.classList.remove("apbot-positioned");
        chatWindow.style.left = "";
        chatWindow.style.top = "";
        try { localStorage.removeItem(positionKey); } catch (error) { /* Storage is optional. */ }
    }

    function setOpen(isOpen) {
        chatWindow.hidden = !isOpen;
        chatbot.classList.toggle("is-open", isOpen);
        if (isOpen && nudge) nudge.hidden = true;
        toggleButton.setAttribute("aria-expanded", String(isOpen));
        toggleButton.setAttribute("aria-label", isOpen ? "Close ApBot" : "Open ApBot");
        if (isOpen) {
            restoreWindowPosition();
            input.focus();
        }
    }

    function scrollToBottom() {
        messages.scrollTop = messages.scrollHeight;
    }

    function addMessage(text, sender) {
        const row = document.createElement("div");
        row.className = "apbot-message apbot-message-" + sender;

        const bubble = document.createElement("div");
        bubble.className = "apbot-bubble";
        bubble.textContent = text;

        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToBottom();
    }

    function addProductCards(products) {
        if (!Array.isArray(products) || products.length === 0) return;

        const list = document.createElement("div");
        list.className = "apbot-products";

        products.forEach(function (product) {
            const card = document.createElement("a");
            card.className = "apbot-product-card";
            card.href = product.url;

            const imageWrap = document.createElement("span");
            imageWrap.className = "apbot-product-image";
            const image = document.createElement("img");
            image.src = product.image_url;
            image.alt = product.name;
            image.loading = "lazy";
            image.addEventListener("error", function () { imageWrap.classList.add("image-unavailable"); image.remove(); });
            imageWrap.appendChild(image);

            const content = document.createElement("span");
            content.className = "apbot-product-content";

            const category = document.createElement("small");
            category.textContent = product.brand || product.category || "Product";

            const name = document.createElement("strong");
            name.textContent = product.name;

            const description = document.createElement("p");
            description.className = "apbot-product-description";
            description.textContent = product.description || "Open the product for full details.";

            if (Number(product.discount_percent || 0) > 0) {
                const sale = document.createElement("span");
                sale.className = "apbot-product-sale";
                const oldPrice = document.createElement("span");
                oldPrice.className = "apbot-product-old-price";
                oldPrice.textContent = "Rs " + Number(product.original_price || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
                const discount = document.createElement("span");
                discount.className = "apbot-product-discount";
                discount.textContent = product.sale_name + " · " + product.discount_percent + "% off";
                sale.appendChild(oldPrice);
                sale.appendChild(discount);
                content.appendChild(category);
                content.appendChild(name);
                content.appendChild(sale);
            } else {
                content.appendChild(category);
                content.appendChild(name);
            }

            content.appendChild(description);

            const details = document.createElement("span");
            details.className = "apbot-product-details";
            const price = document.createElement("b");
            price.textContent = "Rs " + Number(product.price || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
            const rating = document.createElement("span");
            rating.textContent = Number(product.rating || 0).toFixed(1) + " / 5";
            details.appendChild(price);
            details.appendChild(rating);
            content.appendChild(details);
            card.appendChild(imageWrap);
            card.appendChild(content);
            list.appendChild(card);
        });

        messages.appendChild(list);
        scrollToBottom();
    }

    function getIntentAction(intent) {
        const actions = {
            recommendation: ["View recommended products", urls.products + "?sort=rating"],
            product_search: ["Browse all products", urls.products],
            product_details: ["Open the product catalog", urls.products],
            similar_products: ["Find similar products", urls.products],
            product_comparison: ["Compare products", urls.products],
            offers: ["Explore Azaadi Sale", urls.sale || (urls.products + "?sort=price_low")],
            order_tracking: ["View my orders", urls.orders],
            cancel_order: ["View my orders", urls.orders],
            cart: ["Open my cart", urls.cart],
            checkout: ["Continue to checkout", urls.checkout],
            payment: ["Continue to checkout", urls.checkout],
            shipping: ["View delivery details", urls.checkout],
            returns: ["View my purchases and return cases", urls.orders],
            account: ["Manage my account", urls.profile]
        };
        return actions[intent] || null;
    }

    function addIntentAction(intent, serverAction) {
        const action = serverAction && serverAction.label && serverAction.url
            ? [serverAction.label, serverAction.url]
            : getIntentAction(intent);
        if (!action || !action[1]) return;

        const row = document.createElement("div");
        row.className = "apbot-message apbot-message-bot apbot-action-row";

        const link = document.createElement("a");
        link.className = "apbot-action";
        link.href = action[1];
        link.textContent = action[0] + "  →";

        row.appendChild(link);
        messages.appendChild(row);
        scrollToBottom();
    }

    function addTypingIndicator() {
        const row = document.createElement("div");
        row.className = "apbot-message apbot-message-bot";
        const bubble = document.createElement("div");
        bubble.className = "apbot-bubble";
        const typing = document.createElement("span");
        typing.className = "apbot-typing";
        typing.innerHTML = "<span></span><span></span><span></span>";
        bubble.appendChild(typing);
        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToBottom();
        return row;
    }

    async function sendMessage(message, showUserMessage) {
        if (!message || input.disabled) return;

        if (showUserMessage !== false) addMessage(message, "user");
        input.value = "";
        input.disabled = true;
        sendButton.disabled = true;
        const typingIndicator = addTypingIndicator();

        try {
            const response = await fetch(urls.api, {
                method: "POST",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify({ message: message })
            });
            const data = await response.json();
            typingIndicator.remove();

            if (!response.ok) {
                addMessage(data.reply || "Please check your message and try again.", "bot");
                return;
            }

            addMessage(data.reply, "bot");
            addProductCards(data.products);
            addIntentAction(data.intent, data.action);
        } catch (error) {
            typingIndicator.remove();
            addMessage("We could not reach the assistant just now. Please try again in a moment.", "bot");
            console.error("ApBot:", error);
        } finally {
            input.disabled = false;
            sendButton.disabled = false;
            input.focus();
        }
    }

    dragHandle.addEventListener("pointerdown", function (event) {
        if (!desktopDragEnabled() || event.target.closest("button")) return;

        const rectangle = chatWindow.getBoundingClientRect();
        dragState = {
            offsetX: event.clientX - rectangle.left,
            offsetY: event.clientY - rectangle.top
        };
        chatWindow.classList.add("is-dragging");
        event.preventDefault();
    });

    document.addEventListener("pointermove", function (event) {
        if (!dragState) return;
        placeWindow(
            event.clientX - dragState.offsetX,
            event.clientY - dragState.offsetY,
            false
        );
    });

    document.addEventListener("pointerup", function () {
        if (!dragState) return;
        dragState = null;
        chatWindow.classList.remove("is-dragging");
        const rectangle = chatWindow.getBoundingClientRect();
        placeWindow(rectangle.left, rectangle.top, true);
    });

    dragHandle.addEventListener("dblclick", function (event) {
        if (event.target.closest("button")) return;
        resetWindowPosition();
    });

    window.addEventListener("resize", function () {
        if (!chatWindow.classList.contains("apbot-positioned") || !desktopDragEnabled()) return;
        const rectangle = chatWindow.getBoundingClientRect();
        placeWindow(rectangle.left, rectangle.top, true);
    });

    toggleButton.addEventListener("click", function () { setOpen(chatWindow.hidden); });
    closeButton.addEventListener("click", function () { setOpen(false); });
    form.addEventListener("submit", function (event) {
        event.preventDefault();
        sendMessage(input.value.trim());
    });
    quickButtons.forEach(function (button) {
        button.addEventListener("click", function () { sendMessage(button.dataset.apbotMessage); });
    });

    if (nudge && nudgeOpen && nudgeClose) {
        nudgeOpen.addEventListener("click", function () {
            nudge.hidden = true;
            setOpen(true);
        });
        nudgeClose.addEventListener("click", function () {
            nudge.hidden = true;
        });

        // Show a compact greeting on every page load without opening the full
        // conversation or sending an automatic message.
        window.setTimeout(function () {
            if (chatWindow.hidden) nudge.hidden = false;
        }, 650);
        window.setTimeout(function () {
            nudge.hidden = true;
        }, 9000);
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !chatWindow.hidden) setOpen(false);
    });
})();
