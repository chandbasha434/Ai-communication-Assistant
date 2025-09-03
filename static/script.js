// Remove Firebase Firestore and related imports, as we'll use our backend API
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-app.js";
import { getAuth, signInAnonymously, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-auth.js";

// GLOBAL VARIABLES - MANDATORY
const appId = typeof __app_id !== 'undefined' ? __app_id : 'default-app-id';

// --- Firebase Initialization and Auth ---
const firebaseConfig = {
    apiKey: "AIzaSyBMTKJOVXOW4P4kdfKCH0oMjmSJgHA8M88",
    authDomain: "svaraflow.firebaseapp.com",
    projectId: "svaraflow"
};

const firebaseApp = initializeApp(firebaseConfig);
const auth = getAuth(firebaseApp);

// UI elements
const emailListView = document.getElementById('email-list-view');
const emailDetailView = document.getElementById('email-detail-view');
const goBackBtn = document.getElementById('go-back-btn');
const sendResponseBtn = document.getElementById('send-response-btn');
const userIdDisplay = document.getElementById('user-id');
const analyticsSection = document.getElementById('analytics-section');
const mainContent = document.getElementById('dashboard-main');
const seedDbBtn = document.getElementById('seed-db-btn');

let currentUserId = null;
let emailsData = [];
let isAuthReady = false;
const BACKEND_URL = '.'; // Use a relative URL since the backend now serves the frontend

onAuthStateChanged(auth, async (user) => {
    if (user) {
        currentUserId = user.uid;
        userIdDisplay.textContent = currentUserId;
        isAuthReady = true;
        console.log("User signed in with UID:", currentUserId);
        loadEmails();
        startPolling(); // Start polling for real-time updates
    } else {
        console.log("No user signed in. Signing in anonymously.");
        try {
            await signInAnonymously(auth);
        } catch (error) {
            console.error("Authentication failed:", error);
            isAuthReady = true;
            showToast("Authentication failed. Please check your Firebase setup. 🚫", 'error');
        }
    }
});

// --- API Call Functions ---

async function loadEmails() {
    if (!currentUserId) {
        console.log("Waiting for user authentication...");
        return;
    }

    emailListView.innerHTML = '<div class="flex justify-center items-center h-48"><div class="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-blue-500"></div></div>';
    
    try {
        const response = await fetch(`${BACKEND_URL}/fetch_emails`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        emailsData = await response.json();
        
        if (emailsData.length === 0) {
            showEmptyState();
        } else {
            renderEmailList(emailsData);
        }
        
        const resolvedCount = emailsData.filter(e => e.status === 'resolved').length;
        const pendingCount = emailsData.filter(e => e.status !== 'resolved').length;
        const sentimentCounts = {
            positive: emailsData.filter(e => e.extractedInfo?.sentiment?.toLowerCase() === 'positive').length,
            neutral: emailsData.filter(e => e.extractedInfo?.sentiment?.toLowerCase() === 'neutral').length,
            negative: emailsData.filter(e => e.extractedInfo?.sentiment?.toLowerCase() === 'negative').length
        };
        const priorityCounts = {
            urgent: emailsData.filter(e => e.extractedInfo?.priority?.toLowerCase() === 'urgent').length,
            notUrgent: emailsData.filter(e => e.extractedInfo?.priority?.toLowerCase() !== 'urgent').length
        };
        updateAnalytics(emailsData.length, resolvedCount, pendingCount, sentimentCounts, priorityCounts);

    } catch (error) {
        console.error("Error fetching emails:", error);
        showToast("Failed to load emails. Please try again later. ⚠️", 'error');
        showErrorMessage("Failed to load emails. Please check your network.");
    }
}

async function getAIResponse(emailBody) {
    try {
        const response = await fetch(`${BACKEND_URL}/generate_response`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email_body: emailBody })
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        if (data.status === "success") {
            return data.ai_response;
        } else {
            throw new Error(data.message);
        }
    } catch (error) {
        console.error("Error generating AI response:", error);
        showToast("Failed to generate AI response. 🚫", 'error');
        return "Failed to generate AI response. Please try again.";
    }
}

// --- Real-time Updates (Polling) ---
function startPolling() {
    setInterval(() => {
        if (emailListView.classList.contains('hidden') === false) {
            loadEmails();
        }
    }, 30000);
}

// --- User Feedback (Toast Notifications) ---
function showToast(message, type = 'success') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        console.error("Toast container not found.");
        return;
    }
    
    const toast = document.createElement('div');
    let bgColor = 'bg-green-500';
    let icon = '✅';

    if (type === 'error') {
        bgColor = 'bg-red-500';
        icon = '🚫';
    } else if (type === 'warning') {
        bgColor = 'bg-yellow-500';
        icon = '⚠️';
    }

    toast.className = `p-4 rounded-md shadow-lg text-white flex items-center space-x-2 transition-all duration-300 transform -translate-y-full opacity-0 ${bgColor}`;
    toast.innerHTML = `
        <span>${icon}</span>
        <span class="text-sm font-medium">${message}</span>
    `;

    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.transform = 'translateY(0)';
        toast.style.opacity = '1';
    }, 50);

    setTimeout(() => {
        toast.style.transform = 'translateY(100%)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

function showEmptyState() {
    emailListView.innerHTML = `
        <div class="text-center p-12 text-gray-500">
            <svg class="mx-auto h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
            <h3 class="mt-2 text-sm font-medium text-gray-900">No emails to display</h3>
            <p class="mt-1 text-sm text-gray-500">
                Filtered emails will appear here.
            </p>
        </div>
    `;
}

function showErrorMessage(message) {
    emailListView.innerHTML = `
        <div class="text-center p-12 text-red-500">
            <h3 class="mt-2 text-sm font-medium">${message}</h3>
        </div>
    `;
}

function renderEmailList(emails) {
    emailListView.innerHTML = '';
    emails.forEach(email => {
        const sentimentClass = email.extractedInfo?.sentiment?.toLowerCase() === 'positive' ? 'bg-green-500/10 text-green-500' :
                               email.extractedInfo?.sentiment?.toLowerCase() === 'negative' ? 'bg-red-500/10 text-red-500' : 'bg-yellow-500/10 text-yellow-500';
        const statusClass = email.status === 'resolved' ? 'bg-green-500/20 text-green-700' : 'bg-blue-500/20 text-blue-700';
        const priorityClass = email.extractedInfo?.priority?.toLowerCase() === 'urgent' ? 'bg-red-500 text-white font-bold' : 'bg-gray-400 text-gray-800';
        
        const customerName = email.extractedInfo?.customer_name || 'Unknown User';
        const requestSummary = email.extractedInfo?.request_summary || 'No summary available.';
        const timestamp = email.timestamp ? new Date(email.timestamp).toLocaleString() : 'N/A';
        const status = email.status || 'N/A';

        const cardHtml = `
            <div class="email-card p-6 rounded-xl shadow-md cursor-pointer border-l-4 ${status === 'pending' ? 'border-indigo-500' : 'border-green-500'}" data-email-id="${email.id}">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm font-medium ${statusClass} rounded-full px-2 py-1">${status}</span>
                    <span class="text-xs font-semibold px-2 py-1 rounded-full ${sentimentClass}">${email.extractedInfo?.sentiment || 'N/A'}</span>
                    <span class="text-xs font-semibold px-2 py-1 rounded-full ${priorityClass}">${email.extractedInfo?.priority || 'N/A'}</span>
                </div>
                <h2 class="text-xl font-semibold text-gray-800">Support Request from ${customerName}</h2>
                <p class="text-gray-600 truncate">${requestSummary}</p>
                <div class="flex justify-between items-center text-xs mt-4 text-gray-400">
                    <span>From: ${email.sender}</span>
                    <span>${timestamp}</span>
                </div>
            </div>
        `;
        emailListView.innerHTML += cardHtml;
    });
}

function updateAnalytics(total, resolved, pending, sentimentCounts, priorityCounts) {
    const totalEmailsEl = document.getElementById('total-emails');
    const resolvedBarEl = document.getElementById('resolved-bar');
    const resolvedCountEl = document.getElementById('resolved-count');
    const pendingCountEl = document.getElementById('pending-count');
    
    // Update total emails and resolved/pending counts
    totalEmailsEl.textContent = total;
    resolvedCountEl.textContent = resolved;
    pendingCountEl.textContent = pending;

    const resolvedPercentage = total > 0 ? (resolved / total) * 100 : 0;
    resolvedBarEl.style.width = `${resolvedPercentage}%`;

    // Update sentiment bars
    const totalSentiment = sentimentCounts.positive + sentimentCounts.neutral + sentimentCounts.negative;
    if (totalSentiment > 0) {
        document.getElementById('sentiment-positive-bar').style.width = `${(sentimentCounts.positive / totalSentiment) * 100}%`;
        document.getElementById('sentiment-neutral-bar').style.width = `${(sentimentCounts.neutral / totalSentiment) * 100}%`;
        document.getElementById('sentiment-negative-bar').style.width = `${(sentimentCounts.negative / totalSentiment) * 100}%`;
    }

    // Update priority bars
    const totalPriority = priorityCounts.urgent + priorityCounts.notUrgent;
    if (totalPriority > 0) {
        document.getElementById('priority-urgent-bar').style.width = `${(priorityCounts.urgent / totalPriority) * 100}%`;
        document.getElementById('priority-not-urgent-bar').style.width = `${(priorityCounts.notUrgent / totalPriority) * 100}%`;
    }
}

emailListView.addEventListener('click', (event) => {
    let card = event.target.closest('.email-card');
    if (card) {
        const emailId = card.dataset.emailId;
        const email = emailsData.find(e => e.id === emailId);
        if (email) {
            showEmailDetail(email);
        }
    }
});

async function showEmailDetail(email) {
    emailListView.classList.add('hidden');
    emailDetailView.classList.remove('hidden');
    
    // Check if the element exists before trying to set its textContent
    const emailSubjectEl = document.getElementById('email-subject');
    if (emailSubjectEl) emailSubjectEl.textContent = email.subject || 'No Subject';

    const emailSenderEl = document.getElementById('email-sender');
    if (emailSenderEl) emailSenderEl.textContent = email.sender || 'Unknown';

    const emailDateEl = document.getElementById('email-date');
    if (emailDateEl) emailDateEl.textContent = new Date(email.timestamp).toLocaleString();
    
    const emailBodyEl = document.getElementById('email-body');
    if (emailBodyEl) emailBodyEl.textContent = email.body || 'No content available.';
    
    const extractedCustomerNameEl = document.getElementById('extracted-customer-name');
    if (extractedCustomerNameEl) extractedCustomerNameEl.textContent = email.extractedInfo?.customer_name || 'N/A';

    const extractedRequestSummaryEl = document.getElementById('extracted-request-summary');
    if (extractedRequestSummaryEl) extractedRequestSummaryEl.textContent = email.extractedInfo?.request_summary || 'N/A';

    const extractedSentimentEl = document.getElementById('extracted-sentiment');
    if (extractedSentimentEl) extractedSentimentEl.textContent = email.extractedInfo?.sentiment || 'N/A';

    const extractedPriorityEl = document.getElementById('extracted-priority');
    if (extractedPriorityEl) extractedPriorityEl.textContent = email.extractedInfo?.priority || 'N/A';
    
    const extractedContactDetailsEl = document.getElementById('extracted-contact-details');
    if (extractedContactDetailsEl) extractedContactDetailsEl.textContent = email.extractedInfo?.contact_details || 'N/A';

    const aiResponseEditor = document.getElementById('ai-response-editor');
    if (aiResponseEditor) {
        aiResponseEditor.value = 'AI is drafting a response...';
        aiResponseEditor.disabled = true;
    }

    const aiResponse = await getAIResponse(email.body);
    if (aiResponseEditor) {
        aiResponseEditor.value = aiResponse;
        aiResponseEditor.disabled = false;
    }
    
    const sendResponseBtnEl = document.getElementById('send-response-btn');
    if (sendResponseBtnEl) sendResponseBtnEl.dataset.emailId = email.id;
}

goBackBtn.addEventListener('click', () => {
    emailDetailView.classList.add('hidden');
    emailListView.classList.remove('hidden');
    loadEmails();
});

sendResponseBtn.addEventListener('click', async () => {
    const emailId = sendResponseBtn.dataset.emailId;
    const finalResponse = document.getElementById('ai-response-editor').value;

    if (finalResponse.trim() === '') {
        showToast("Please write a response before sending. ⚠️", 'warning');
        return;
    }
    
    sendResponseBtn.disabled = true;
    sendResponseBtn.textContent = 'Sending...';

    try {
        const response = await fetch(`${BACKEND_URL}/update_email_status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                email_id: emailId, 
                final_response: finalResponse 
            })
        });

        const data = await response.json();
        
        if (data.status === "success") {
            showToast("Response sent successfully! ✅");
            goBackBtn.click();
        } else {
            throw new Error(data.message);
        }
    } catch (error) {
        showToast("Failed to send response. Please try again. 🚫", 'error');
        console.error("Error sending response:", error);
    } finally {
        sendResponseBtn.disabled = false;
        sendResponseBtn.textContent = 'Send Response';
    }
});

seedDbBtn.addEventListener('click', async () => {
    seedDbBtn.disabled = true;
    seedDbBtn.textContent = 'Seeding...';
    showToast("Seeding database with mock emails...", 'warning');

    try {
        const response = await fetch(`${BACKEND_URL}/seed_emails`, {
            method: 'POST'
        });
        const data = await response.json();
        if (data.status === "success") {
            showToast("Database seeded successfully! ✅");
            loadEmails();
        } else {
            throw new Error(data.message);
        }
    } catch (error) {
        showToast("Failed to seed database. It may already be seeded. 🚫", 'error');
        console.error("Error seeding database:", error);
    } finally {
        seedDbBtn.disabled = false;
        seedDbBtn.textContent = 'Seed Database';
    }
});