document.addEventListener('DOMContentLoaded', function() {
    const messagesContainer = document.querySelector('.messages-container');
    const messageForm = document.querySelector('.message-form');
    const messageInput = document.querySelector('.message-input');
    const sendButton = document.querySelector('.send-button');
    
    // Store session ID in a variable
    let sessionId = localStorage.getItem('munim_session_id') || null;
    let sessionState = localStorage.getItem('munim_session_state') || 'idle';
    
    // Setup menu interaction handling
    setupMenuHandler();

    // Function to handle menu interactions
    function setupMenuHandler() {
        // Create a mutation observer to watch for added content
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                    // Look for menu sections in added content
                    setTimeout(() => {
                        const sections = document.querySelectorAll('.menu-section');
                        sections.forEach(section => {
                            const header = section.querySelector('div:first-child');
                            const content = section.querySelector('div:last-child');
                            
                            if (header && content && !header.hasAttribute('data-handler-set')) {
                                // Mark header to avoid duplicate handlers
                                header.setAttribute('data-handler-set', 'true');
                                
                                // Add click handler
                                header.style.cursor = 'pointer';
                                header.addEventListener('click', function() {
                                    if (content.style.display === 'none') {
                                        content.style.display = 'block';
                                    } else {
                                        content.style.display = 'none';
                                    }
                                });
                            }
                        });
                    }, 100); // Short delay to ensure DOM is updated
                }
            });
        });
        
        // Start observing the message container
        observer.observe(messagesContainer, {
            childList: true,
            subtree: true
        });
    }

    // Function to format date for chat messages
    function formatMessageTime() {
        const now = new Date();
        const hours = String(now.getHours()).padStart(2, '0');
        const minutes = String(now.getMinutes()).padStart(2, '0');
        return `${hours}:${minutes}`;
    }

    // Function to add a message to the chat
    function addMessage(content, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', isUser ? 'message-user' : 'message-bot');

        const contentDiv = document.createElement('div');
        contentDiv.classList.add('message-content');
        contentDiv.innerHTML = content; // Allow HTML for formatting ledgers etc.

        const timeDiv = document.createElement('div');
        timeDiv.classList.add('message-time');
        timeDiv.textContent = formatMessageTime();

        messageDiv.appendChild(contentDiv);
        messageDiv.appendChild(timeDiv);
        messagesContainer.appendChild(messageDiv);

        // Scroll to bottom
        scrollToBottom();
        
        // For bot messages, look for success/failure indicators
        if (!isUser) {
            if (content.includes('invoice created') || 
                content.includes('successfully generated') || 
                content.includes('recorded successfully')) {
                showToast('Operation completed successfully', 'success');
            } else if (content.includes('error') || content.includes('failed') || 
                      content.includes('invalid') || content.includes('unable to')) {
                // Don't show error toasts for normal error messages to avoid duplication
                if (!content.startsWith('Error:')) {
                    showToast('An error occurred', 'error');
                }
            }
        }
    }

    // Function to show loading indicator
    function showLoadingIndicator() {
        const indicatorDiv = document.createElement('div');
        indicatorDiv.classList.add('typing-indicator');
        indicatorDiv.innerHTML = `
            <div class="dot"></div>
            <div class="dot"></div>
            <div class="dot"></div>
        `;
        indicatorDiv.id = 'loading-indicator';
        messagesContainer.appendChild(indicatorDiv);
        scrollToBottom();
    }

    // Function to hide loading indicator
    function hideLoadingIndicator() {
        const indicator = document.getElementById('loading-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    // Function to scroll chat to bottom
    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // Make functions available globally
    window.addMessage = addMessage;
    window.showLoadingIndicator = showLoadingIndicator;
    window.hideLoadingIndicator = hideLoadingIndicator;
    window.scrollToBottom = scrollToBottom;

    // Add welcome message when page loads
    window.onload = function() {
        const welcomeMessage = `👋 Welcome to <strong>Munim AI</strong> — your trusted digital accountant.

📈 From GST invoices and expense tracking to stock, ledgers, and reminders — I do it all.  
🧾 Generate invoices in 30 seconds.  
📊 Track profit, send reminders, and never miss a due payment.  
`;

        const quickActions = `<div class="quick-actions">
            <button class="quick-action-btn" onclick="sendQuickCommand('menu')">View Menu</button>
            <button class="quick-action-btn" onclick="sendQuickCommand('Create invoice')">Create Invoice</button>
            <button class="quick-action-btn" onclick="sendQuickCommand('Record expense')">Record Expense</button>
            <button class="quick-action-btn" onclick="sendQuickCommand('Show financial report')">Financial Report</button>
            <button class="quick-action-btn help-btn" onclick="sendQuickCommand('help')"><i class="fas fa-question-circle"></i> Help</button>
        </div>
        <p style="margin-top: 10px; font-style: italic; font-size: 14px;">You can also type your own questions or requests anytime!</p>`;

        // Add welcome messages with rich formatting and slight delay for visual effect
        setTimeout(() => {
            addMessage(welcomeMessage, false);
            
            // Add quick action buttons after a short delay
            setTimeout(() => {
                addMessage(quickActions, false);
            }, 700);
        }, 500);
    };
    
    // Function to send a quick command when a quick action button is clicked
    window.sendQuickCommand = function(command) {
        // Add user message to chat
        addMessage(command, true);
        
        // Show loading
        showLoadingIndicator();
        
        // Send message to backend
        fetch('/api/message', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                message: command,
                session_id: sessionId
            })
        })
        .then(response => response.json())
        .then(data => {
            // Hide loading indicator
            hideLoadingIndicator();
            
            // Update session information
            if (data.session_id) {
                sessionId = data.session_id;
                localStorage.setItem('munim_session_id', sessionId);
            }
            
            if (data.session_state) {
                sessionState = data.session_state;
                localStorage.setItem('munim_session_state', sessionState);
            }
            
            // Add bot response
            if (data.response) {
                addMessage(data.response, false);
            } else if (data.error) {
                addMessage(`Error: ${data.error}`, false);
            }
        })
        .catch(error => {
            hideLoadingIndicator();
            addMessage('Sorry, I had trouble processing that request. Please try again.', false);
            console.error('Error:', error);
        });
    };

    // Handle message submission
    messageForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        const message = messageInput.value.trim();
        if (!message) return;
        
        // Add user message to chat
        addMessage(message, true);
        
        // Clear input
        messageInput.value = '';
        
        // Disable input while processing
        messageInput.disabled = true;
        sendButton.disabled = true;
        
        // Show loading
        showLoadingIndicator();
        
        // Send message to backend with session ID
        fetch('/api/message', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                message: message,
                session_id: sessionId
            })
        })
        .then(response => response.json())
        .then(data => {
            // Hide loading indicator
            hideLoadingIndicator();
            
            // Update session information
            if (data.session_id) {
                sessionId = data.session_id;
                localStorage.setItem('munim_session_id', sessionId);
            }
            
            if (data.session_state) {
                sessionState = data.session_state;
                localStorage.setItem('munim_session_state', sessionState);
            }
            
            // Add bot response
            if (data.response) {
                addMessage(data.response, false);
            } else if (data.error) {
                addMessage(`Error: ${data.error}`, false);
            }
        })
        .catch(error => {
            hideLoadingIndicator();
            addMessage('Sorry, I had trouble processing that request. Please try again.', false);
            console.error('Error:', error);
        })
        .finally(() => {
            // Re-enable input
            messageInput.disabled = false;
            sendButton.disabled = false;
            messageInput.focus();
        });
    });

    // Enable/disable send button based on input
    messageInput.addEventListener('input', function() {
        sendButton.disabled = !this.value.trim();
    });

    // Focus input field when page loads
    messageInput.focus();
});

// Function to show toast notifications for user feedback
function showToast(message, type = 'info') {
    // Remove any existing toast
    const existingToast = document.querySelector('.toast-notification');
    if (existingToast) {
        existingToast.remove();
    }
    
    // Create toast element
    const toast = document.createElement('div');
    toast.classList.add('toast-notification');
    
    // Add specific styling based on type
    if (type === 'success') {
        toast.classList.add('success');
        toast.innerHTML = `<i class="fas fa-check-circle"></i> ${message}`;
    } else if (type === 'error') {
        toast.classList.add('error');
        toast.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
    } else {
        toast.innerHTML = `<i class="fas fa-info-circle"></i> ${message}`;
    }
    
    // Add to document
    document.body.appendChild(toast);
    
    // Remove after timeout (animation handles fading)
    setTimeout(() => {
        toast.remove();
    }, 3000);
}
