(function () {
    "use strict";

    const chatbot = document.getElementById("apbot");
    if (!chatbot) return;

    const urls = {
        api:      chatbot.dataset.apiUrl,
        products: chatbot.dataset.productsUrl,
        orders:   chatbot.dataset.ordersUrl,
        cart:     chatbot.dataset.cartUrl,
        checkout: chatbot.dataset.checkoutUrl,
        profile:  chatbot.dataset.profileUrl
    };

    const toggleButton = document.getElementById("apbotToggle");
    const closeButton  = document.getElementById("apbotClose");
    const chatWindow   = document.getElementById("apbotWindow");
    const dragHandle   = document.getElementById("apbotDragHandle");
    const messages     = document.getElementById("apbotMessages");
    const form         = document.getElementById("apbotForm");
    const input        = document.getElementById("apbotInput");
    const sendButton   = document.getElementById("apbotSend");
    const quickButtons = document.querySelectorAll("[data-apbot-message]");
    const positionKey  = "zilocart-apbot-position";
    let dragState = null;

    // ------------------------------------------------------------------
    // Conversation history
    // Keeps the last MAX_HISTORY turns so the backend can resolve context
    // (e.g. "how much?" after viewing a product list, pronoun references).
    // Each entry: { role: "user"|"bot", content: string, intent?: string }
    // ------------------------------------------------------------------
    const MAX_HISTORY = 6;
    let conversationHistory = [];

    function pushHistory(role, content, intent) {
        const entry = { role: role, content: content };
        if (role === "bot" && intent) {
            entry.intent = intent;
        }
        conversationHistory.push(entry);
        // Keep only the most recent MAX_HISTORY entries
        if (conversationHistory.length > MAX_HISTORY) {
            conversationHistory = conversationHistory.slice(-MAX_HISTORY);
        }
    }

    // ------------------------------------------------------------------
    // Window positioning / drag
    // ------------------------------------------------------------------
    function desktopDragEnabled() {
        return window.matchMedia("(min-width: 576px)").matches;
    }

    function keepInsideViewport(left, top) {
        const gap     = 10;
        const maxLeft = Math.max(gap, window.innerWidth  - chatWindow.offsetWidth  - gap);
        const maxTop  = Math.max(gap, window.innerHeight - chatWindow.offsetHeight - gap);
        return {
            left: Math.min(Math.max(gap, left), maxLeft),
            top:  Math.min(Math.max(gap, top),  maxTop)
        };
    }

    function placeWindow(left, top, savePosition) {
        if (!desktopDragEnabled()) return;
        const safe = keepInsideViewport(left, top);
        chatWindow.classList.add("apbot-positioned");
        chatWindow.style.left = safe.left + "px";
        chatWindow.style.top  = safe.top  + "px";
        if (savePosition) {
            try { localStorage.setItem(positionKey, JSON.stringify(safe)); } catch (e) { /* optional */ }
        }
    }

    function restoreWindowPosition() {
        if (!desktopDragEnabled()) return;
        try {
            const saved = JSON.parse(localStorage.getItem(positionKey));
            if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.top)) {
                placeWindow(saved.left, saved.top, false);
            }
        } catch (e) { /* use default position */ }
    }

    function resetWindowPosition() {
        chatWindow.classList.remove("apbot-positioned");
        chatWindow.style.left = "";
        chatWindow.style.top  = "";
        try { localStorage.removeItem(positionKey); } catch (e) { /* optional */ }
    }

    function setOpen(isOpen) {
        chatWindow.hidden = !isOpen;
        chatbot.classList.toggle("is-open", isOpen);
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

    // ------------------------------------------------------------------
    // Message rendering
    // ------------------------------------------------------------------
    function addMessage(text, sender) {
        const row    = document.createElement("div");
        row.className = "apbot-message apbot-message-" + sender;

        const bubble = document.createElement("div");
        bubble.className  = "apbot-bubble";
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
            image.src     = product.image_url;
            image.alt     = product.name;
            image.loading = "lazy";
            image.addEventListener("error", function () {
                imageWrap.classList.add("image-unavailable");
                image.remove();
            });
            imageWrap.appendChild(image);

            const content  = document.createElement("span");
            content.className = "apbot-product-content";

            const category = document.createElement("small");
            category.textContent = product.brand || product.category || "Product";

            const name = document.createElement("strong");
            name.textContent = product.name;

            const details = document.createElement("span");
            details.className = "apbot-product-details";
            const price  = document.createElement("b");
            price.textContent = "Rs " + Number(product.price || 0).toLocaleString(
                undefined, { maximumFractionDigits: 0 }
            );
            const rating = document.createElement("span");
            rating.textContent = Number(product.rating || 0).toFixed(1) + " / 5";
            details.appendChild(price);
            details.appendChild(rating);

            content.appendChild(category);
            content.appendChild(name);
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
            recommendation:     ["View recommended products",  urls.products + "?sort=rating"],
            product_search:     ["Browse all products",        urls.products],
            product_details:    ["Open the product catalog",   urls.products],
            similar_products:   ["Find similar products",      urls.products],
            product_comparison: ["Compare products",           urls.products],
            offers:             ["Browse by lowest price",     urls.products + "?sort=price_low"],
            order_tracking:     ["View my orders",             urls.orders],
            cancel_order:       ["View my orders",             urls.orders],
            cart:               ["Open my cart",               urls.cart],
            checkout:           ["Continue to checkout",       urls.checkout],
            payment:            ["Continue to checkout",       urls.checkout],
            shipping:           ["View delivery details",      urls.checkout],
            account:            ["Manage my account",          urls.profile]
        };
        return actions[intent] || null;
    }

    function addIntentAction(intent) {
        const action = getIntentAction(intent);
        if (!action || !action[1]) return;

        const row  = document.createElement("div");
        row.className = "apbot-message apbot-message-bot apbot-action-row";

        const link = document.createElement("a");
        link.className   = "apbot-action";
        link.href        = action[1];
        link.textContent = action[0] + "  →";

        row.appendChild(link);
        messages.appendChild(row);
        scrollToBottom();
    }

    function addTypingIndicator() {
        const row    = document.createElement("div");
        row.className = "apbot-message apbot-message-bot";
        const bubble = document.createElement("div");
        bubble.className = "apbot-bubble";
        const typing = document.createElement("span");
        typing.className  = "apbot-typing";
        typing.innerHTML  = "<span></span><span></span><span></span>";
        bubble.appendChild(typing);
        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToBottom();
        return row;
    }

    // ------------------------------------------------------------------
    // Send message + history to the API
    // ------------------------------------------------------------------
    async function sendMessage(message) {
        if (!message || input.disabled) return;

        addMessage(message, "user");
        input.value = "";
        input.disabled   = true;
        sendButton.disabled = true;
        const typingIndicator = addTypingIndicator();

        // Record the user turn in history before the request so the backend
        // always has the full context including the current message.
        pushHistory("user", message);

        try {
            const response = await fetch(urls.api, {
                method:  "POST",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify({
                    message: message,
                    // Send a copy of the current history (includes the user
                    // turn we just pushed above).
                    history: conversationHistory.slice()
                })
            });

            const data = await response.json();
            typingIndicator.remove();

            if (!response.ok) {
                addMessage(data.reply || "Please check your message and try again.", "bot");
                // Record a generic bot turn so history stays coherent
                pushHistory("bot", data.reply || "", "unknown");
                return;
            }

            addMessage(data.reply, "bot");
            addProductCards(data.products);
            addIntentAction(data.intent);

            // Record the bot turn with its resolved intent so the next
            // message can use it for context resolution.
            pushHistory("bot", data.reply, data.intent);

        } catch (error) {
            typingIndicator.remove();
            addMessage(
                "We could not reach the assistant just now. Please try again in a moment.",
                "bot"
            );
            console.error("ApBot:", error);
        } finally {
            input.disabled      = false;
            sendButton.disabled = false;
            input.focus();
        }
    }

    // ------------------------------------------------------------------
    // Drag behaviour
    // ------------------------------------------------------------------
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

    // ------------------------------------------------------------------
    // Event listeners
    // ------------------------------------------------------------------
    toggleButton.addEventListener("click", function () { setOpen(chatWindow.hidden); });
    closeButton.addEventListener("click",  function () { setOpen(false); });
    form.addEventListener("submit", function (event) {
        event.preventDefault();
        sendMessage(input.value.trim());
    });
    quickButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            sendMessage(button.dataset.apbotMessage);
        });
    });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !chatWindow.hidden) setOpen(false);
    });
})();
