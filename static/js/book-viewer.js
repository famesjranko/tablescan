/**
 * Book Viewer Alpine.js Component
 *
 * PDF rendering and navigation for book-style spread layout.
 * Uses PDF.js for rendering and provides zoom, navigation, and selection features.
 */

console.log('[BookViewer] Module loading, importing PDF.js from CDN...');

import * as pdfjsLib from 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.min.mjs';

console.log('[BookViewer] PDF.js imported successfully:', pdfjsLib);

pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.worker.min.mjs';

// Global storage for PDF documents to avoid Alpine proxy issues
const pdfDocStorage = new Map();

// Global storage for render tasks to avoid Alpine proxy issues with PDF.js private members
const renderTaskStorage = new Map();

export function createBookViewer(config) {
    const instanceId = `pdf_${config.reportId}_${Date.now()}`;

    return {
        // Configuration
        reportId: config.reportId,
        pdfUrl: config.pdfUrl,
        extractionMode: config.extractionMode || 'auto',
        _pdfInstanceId: instanceId,

        // PDF state - use global storage to avoid proxy issues
        getPdfDoc() { return pdfDocStorage.get(this._pdfInstanceId); },
        setPdfDoc(doc) { pdfDocStorage.set(this._pdfInstanceId, doc); },
        totalPages: 0,
        currentSpread: 0,
        leftPageNum: 0,
        rightPageNum: 0,
        pageMetadata: [], // {width, height} for each page

        // UI state
        zoom: 100,
        mode: 'view',
        loading: true,
        renderingPages: false,
        canvasReady: false,
        error: null,
        renderError: null,

        // Page input for direct navigation
        gotoPageInput: '',

        // Selection state
        selections: [],
        hoveredSelectionId: null,
        selectionStyleVersion: 0,

        // Render version to prevent stale renders from completing
        _renderVersion: 0,
        isDrawing: false,
        drawingPage: null,
        startX: 0,
        startY: 0,
        currentX: 0,
        currentY: 0,

        // Extraction state
        extracting: false,
        extractProgress: null,
        extractError: null,
        extractTaskId: null,
        partialSuccess: null, // Tracks partial success info

        /**
         * Initialize the viewer - load PDF and selections
         */
        async init() {
            console.log('[BookViewer] init() called, pdfUrl:', this.pdfUrl);
            try {
                this.loading = true;
                this.error = null;

                // Load the PDF document
                console.log('[BookViewer] Loading PDF document...');
                const loadingTask = pdfjsLib.getDocument(this.pdfUrl);
                this.setPdfDoc(await loadingTask.promise);
                this.totalPages = this.getPdfDoc().numPages;
                this.gotoPageInput = '1';
                console.log('[BookViewer] PDF loaded, totalPages:', this.totalPages);

                // Load page metadata (dimensions for all pages)
                console.log('[BookViewer] Loading page metadata...');
                await this.loadPageMetadata();

                // Load existing selections from API
                console.log('[BookViewer] Loading selections...');
                await this.loadSelections();

                // Render the first spread
                console.log('[BookViewer] Rendering spread...');
                await this.renderSpread();

                console.log('[BookViewer] Init complete, setting loading=false');
                this.loading = false;
                // Wait for TWO frames to ensure browser has completed layout after container becomes visible
                // First frame: container becomes visible, second frame: layout is computed
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                // Increment version to force Alpine to re-evaluate getSelectionStyle()
                this.selectionStyleVersion++;
            } catch (err) {
                console.error('[BookViewer] Error loading PDF:', err);
                this.error = err.message || 'Failed to load PDF document';
                this.loading = false;
            }
        },

        /**
         * Load page metadata (width, height) for all pages
         */
        async loadPageMetadata() {
            this.pageMetadata = [];
            for (let i = 1; i <= this.totalPages; i++) {
                try {
                    const page = await this.getPdfDoc().getPage(i);
                    const viewport = page.getViewport({ scale: 1.0 });
                    this.pageMetadata.push({
                        width: viewport.width,
                        height: viewport.height,
                        rotation: page.rotate
                    });
                } catch (err) {
                    console.error(`Error loading metadata for page ${i}:`, err);
                    this.pageMetadata.push({ width: 612, height: 792, rotation: 0 }); // Default letter size
                }
            }
        },

        /**
         * Load selections from API
         */
        async loadSelections() {
            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
                const response = await fetch(`/api/reports/${this.reportId}/selections/`, {
                    headers: {
                        'X-CSRFToken': csrfToken
                    }
                });
                if (response.ok) {
                    this.selections = await response.json();
                }
            } catch (err) {
                console.error('Error loading selections:', err);
            }
        },

        /**
         * Render current spread (two pages side-by-side)
         */
        async renderSpread() {
            // Increment version to invalidate any in-flight renders
            const myVersion = ++this._renderVersion;

            this.canvasReady = false;
            this.leftPageNum = this.currentSpread * 2 + 1;
            this.rightPageNum = this.currentSpread * 2 + 2;
            this.renderError = null;
            this.renderingPages = true;

            try {
                // Render left page
                await this.renderPage(this.leftPageNum, 'left-page-canvas');

                // Abort if a newer render started
                if (myVersion !== this._renderVersion) return;

                // Render right page if it exists
                if (this.rightPageNum <= this.totalPages) {
                    await this.renderPage(this.rightPageNum, 'right-page-canvas');
                } else {
                    // Clear right canvas for single page or odd page count
                    this.clearCanvas('right-page-canvas');
                }

                // Abort if a newer render started
                if (myVersion !== this._renderVersion) return;

                // Wait for browser to layout canvas before updating selections
                // getBoundingClientRect() needs a frame to return correct dimensions
                await new Promise(resolve => requestAnimationFrame(resolve));
                this.canvasReady = true;
                // Force Alpine to re-evaluate selection styles by reassigning array
                // This triggers x-for to re-render with correct canvas dimensions
                this.selections = [...this.selections];
            } catch (err) {
                // Ignore errors from superseded renders
                if (myVersion !== this._renderVersion) return;
                console.error('Error rendering spread:', err);
                this.renderError = err.message || 'Failed to render pages';
            } finally {
                // Only clear renderingPages if this is still the active render
                if (myVersion === this._renderVersion) {
                    this.renderingPages = false;
                }
            }
        },

        /**
         * Render a single page to canvas
         */
        async renderPage(pageNum, canvasId) {
            if (pageNum < 1 || pageNum > this.totalPages) return;

            const canvas = document.getElementById(canvasId);
            if (!canvas) {
                console.error(`Canvas ${canvasId} not found`);
                return;
            }

            // Cancel any pending render task for this canvas (use global storage to avoid proxy issues)
            const taskKey = `${this._pdfInstanceId}_${canvasId}`;
            const existingTask = renderTaskStorage.get(taskKey);
            if (existingTask) {
                existingTask.cancel();
                renderTaskStorage.delete(taskKey);
            }

            try {
                const page = await this.getPdfDoc().getPage(pageNum);
                const scale = 1.5; // Base scale for good quality
                const viewport = page.getViewport({ scale });

                const ctx = canvas.getContext('2d');
                canvas.width = viewport.width;
                canvas.height = viewport.height;

                // Store PDF dimensions in dataset for coordinate conversion
                // These are the actual PDF page dimensions (unscaled)
                const metadata = this.pageMetadata[pageNum - 1];
                canvas.dataset.pdfWidth = metadata.width;
                canvas.dataset.pdfHeight = metadata.height;
                canvas.dataset.pageNum = pageNum;
                canvas.dataset.scale = scale;

                const renderTask = page.render({
                    canvasContext: ctx,
                    viewport: viewport
                });
                renderTaskStorage.set(taskKey, renderTask);

                await renderTask.promise;
                renderTaskStorage.delete(taskKey);
            } catch (err) {
                renderTaskStorage.delete(taskKey);
                // Ignore cancellation errors - they're expected when navigating quickly
                if (err.name === 'RenderingCancelledException') {
                    return;
                }
                console.error(`Error rendering page ${pageNum}:`, err);
                this.clearCanvas(canvasId);
                throw new Error(`Failed to render page ${pageNum}`);
            }
        },

        /**
         * Clear a canvas
         */
        clearCanvas(canvasId) {
            const canvas = document.getElementById(canvasId);
            if (canvas) {
                const ctx = canvas.getContext('2d');
                canvas.width = 0;
                canvas.height = 0;
                delete canvas.dataset.pdfWidth;
                delete canvas.dataset.pdfHeight;
                delete canvas.dataset.pageNum;
                delete canvas.dataset.scale;
            }
        },

        /**
         * Navigate to previous spread
         */
        prevSpread() {
            if (this.currentSpread > 0) {
                this.currentSpread--;
                this.gotoPageInput = String(this.leftPageNum - 2);
                this.renderSpread();
            }
        },

        /**
         * Navigate to next spread
         */
        nextSpread() {
            if (this.hasNextSpread()) {
                this.currentSpread++;
                this.gotoPageInput = String(this.leftPageNum + 2);
                this.renderSpread();
            }
        },

        /**
         * Check if there's a next spread
         */
        hasNextSpread() {
            return (this.currentSpread + 1) * 2 < this.totalPages;
        },

        /**
         * Get label for current spread
         */
        getSpreadLabel() {
            if (this.totalPages === 0) return '';
            const left = this.leftPageNum;
            const right = Math.min(this.rightPageNum, this.totalPages);
            if (left === right) {
                return `Page ${left} of ${this.totalPages}`;
            }
            return `Pages ${left}-${right} of ${this.totalPages}`;
        },

        /**
         * Check if a page is currently visible in the spread
         */
        isPageVisible(pageNum) {
            return pageNum === this.leftPageNum || pageNum === this.rightPageNum;
        },

        /**
         * Select a table - highlight it and navigate only if needed
         */
        selectTable(sel) {
            // Always highlight the selection
            this.hoveredSelectionId = sel.id;

            // Only navigate if the page isn't already visible
            if (!this.isPageVisible(sel.page_num)) {
                this.goToPage(sel.page_num);
            }
        },

        /**
         * Navigate to a specific page (internal method)
         */
        goToPage(pageNum) {
            if (pageNum < 1 || pageNum > this.totalPages) return;
            const targetSpread = Math.floor((pageNum - 1) / 2);
            // Skip if already on this spread
            if (targetSpread === this.currentSpread && this.canvasReady) return;
            this.currentSpread = targetSpread;
            this.gotoPageInput = String(pageNum);
            this.renderSpread();
        },

        /**
         * Navigate to page from input field
         */
        goToPageFromInput() {
            const pageNum = parseInt(this.gotoPageInput, 10);
            if (isNaN(pageNum)) {
                this.gotoPageInput = String(this.leftPageNum);
                return;
            }

            // Validate range
            if (pageNum < 1) {
                this.gotoPageInput = '1';
                this.goToPage(1);
            } else if (pageNum > this.totalPages) {
                this.gotoPageInput = String(this.totalPages);
                this.goToPage(this.totalPages);
            } else {
                this.goToPage(pageNum);
            }
        },

        /**
         * Handle Enter key on page input
         */
        handlePageInputKeydown(event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                this.goToPageFromInput();
                event.target.blur();
            }
        },

        /**
         * Zoom in by 25%
         */
        zoomIn() {
            if (this.zoom < 200) {
                this.zoom = Math.min(200, this.zoom + 25);
            }
        },

        /**
         * Zoom out by 25%
         */
        zoomOut() {
            if (this.zoom > 50) {
                this.zoom = Math.max(50, this.zoom - 25);
            }
        },

        /**
         * Get selections for a specific page
         */
        getSelectionsForPage(pageNum) {
            return this.selections.filter(s => s.page_num === pageNum);
        },

        /**
         * Set the currently hovered selection ID for highlighting correlation
         * @param {number|null} id - Selection ID or null to clear
         */
        setHoveredSelection(id) {
            this.hoveredSelectionId = id;
        },

        /**
         * Get formatted label for a selection (e.g., "#1 - Page 2 (upper)")
         * @param {Object} sel - Selection object
         * @param {number} idx - Index in selections array
         * @returns {string}
         */
        getSelectionLabel(sel, idx) {
            const index = idx + 1;
            let position = '';
            // Add position hint based on y1 coordinate (percentage)
            if (sel.y1 < 33) {
                position = ' (upper)';
            } else if (sel.y1 < 66) {
                position = ' (middle)';
            } else {
                position = ' (lower)';
            }

            // Add confidence for YOLO detections
            let confidence = '';
            if (sel.source === 'yolo' && sel.confidence != null) {
                confidence = ` · ${Math.round(sel.confidence * 100)}%`;
            }

            return `#${index} - Page ${sel.page_num}${position}${confidence}`;
        },

        /**
         * Calculate selection box style for overlay
         */
        getSelectionStyle(sel, side) {
            // Reference reactive properties to force Alpine to re-evaluate when they change
            const _version = this.selectionStyleVersion;
            const _hovered = this.hoveredSelectionId; // Also track hover changes
            if (!this.canvasReady) {
                return { display: 'none' };
            }
            const canvas = document.getElementById(`${side}-page-canvas`);
            if (!canvas || canvas.width === 0) {
                return { display: 'none' };
            }

            // Use CSS display dimensions since overlay is positioned in CSS pixels
            const rect = canvas.getBoundingClientRect();
            // Container might be visible but not yet laid out - wait for valid dimensions
            if (rect.width === 0 || rect.height === 0) {
                return { display: 'none' };
            }
            const scaleX = rect.width / 100;
            const scaleY = rect.height / 100;

            // Clip coordinates to [0, 100] range and inset edges slightly for rounded corners
            // Inset by ~1% at edges to avoid clipping by container's border-radius
            const edgeInset = 1.0;
            const x1 = sel.x1 <= 0 ? edgeInset : Math.min(100, sel.x1);
            const y1 = sel.y1 <= 0 ? edgeInset : Math.min(100, sel.y1);
            const x2 = sel.x2 >= 100 ? (100 - edgeInset) : Math.max(0, sel.x2);
            const y2 = sel.y2 >= 100 ? (100 - edgeInset) : Math.max(0, sel.y2);

            const style = {
                left: (x1 * scaleX) + 'px',
                top: (y1 * scaleY) + 'px',
                width: ((x2 - x1) * scaleX) + 'px',
                height: ((y2 - y1) * scaleY) + 'px'
            };

            // Add highlight styles inline when this selection is hovered
            if (this.hoveredSelectionId === sel.id) {
                style.borderWidth = '3px';
                style.borderColor = '#3B82F6';
                style.background = 'rgba(59, 130, 246, 0.15)';
                style.boxShadow = '0 0 16px rgba(59, 130, 246, 0.6)';
                style.zIndex = '10';
            }

            return style;
        },

        /**
         * Calculate preview box style while drawing
         */
        getDrawingPreviewStyle(side) {
            if (!this.isDrawing || this.drawingPage !== side) {
                return { display: 'none' };
            }

            // Handle dragging in any direction
            const left = Math.min(this.startX, this.currentX);
            const top = Math.min(this.startY, this.currentY);
            const width = Math.abs(this.currentX - this.startX);
            const height = Math.abs(this.currentY - this.startY);

            return {
                left: left + 'px',
                top: top + 'px',
                width: width + 'px',
                height: height + 'px'
            };
        },

        /**
         * Start drawing a selection
         */
        startSelection(event, side) {
            const container = event.target.closest('.page-container');
            const canvas = container?.querySelector('canvas');
            if (!canvas || canvas.width === 0) return;

            const rect = canvas.getBoundingClientRect();
            this.isDrawing = true;
            this.drawingPage = side;
            this.startX = event.clientX - rect.left;
            this.startY = event.clientY - rect.top;
            this.currentX = this.startX;
            this.currentY = this.startY;
        },

        /**
         * Update selection during drag
         */
        updateSelection(event) {
            if (!this.isDrawing) return;

            const container = document.getElementById(`${this.drawingPage}-page-container`);
            const canvas = container?.querySelector('canvas');
            if (!canvas) return;

            // Use CSS display size (rect) since mouse coords are in CSS pixels
            const rect = canvas.getBoundingClientRect();
            this.currentX = Math.max(0, Math.min(event.clientX - rect.left, rect.width));
            this.currentY = Math.max(0, Math.min(event.clientY - rect.top, rect.height));
        },

        /**
         * End selection and save to API
         */
        async endSelection(event) {
            if (!this.isDrawing) return;
            this.isDrawing = false;

            const container = document.getElementById(`${this.drawingPage}-page-container`);
            const canvas = container?.querySelector('canvas');
            if (!canvas) return;

            const pageNum = this.drawingPage === 'left' ? this.leftPageNum : this.rightPageNum;

            // Convert to percentage coordinates
            // Use getBoundingClientRect() for display size since mouse coords are in CSS pixels
            const rect = canvas.getBoundingClientRect();
            const x1 = Math.min(this.startX, this.currentX) / rect.width * 100;
            const y1 = Math.min(this.startY, this.currentY) / rect.height * 100;
            const x2 = Math.max(this.startX, this.currentX) / rect.width * 100;
            const y2 = Math.max(this.startY, this.currentY) / rect.height * 100;

            // Minimum size check (ignore accidental clicks)
            if (Math.abs(x2 - x1) < 2 || Math.abs(y2 - y1) < 2) {
                return;
            }

            await this.createSelection(pageNum, x1, y1, x2, y2);
        },

        /**
         * Create a new selection via API
         */
        async createSelection(pageNum, x1, y1, x2, y2) {
            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
                const response = await fetch(`/api/reports/${this.reportId}/selections/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({
                        page_num: pageNum,
                        x1: x1,
                        y1: y1,
                        x2: x2,
                        y2: y2,
                        source: 'manual'
                    })
                });

                if (response.ok) {
                    const newSelection = await response.json();
                    this.selections.push(newSelection);
                } else {
                    const error = await response.text();
                    console.error('Failed to create selection:', error);
                }
            } catch (err) {
                console.error('Error creating selection:', err);
            }
        },

        /**
         * Delete a selection via API
         */
        async deleteSelection(selId) {
            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
                const response = await fetch(`/api/reports/${this.reportId}/selections/${selId}/`, {
                    method: 'DELETE',
                    headers: {
                        'X-CSRFToken': csrfToken
                    }
                });

                if (response.ok) {
                    this.selections = this.selections.filter(s => s.id !== selId);
                } else {
                    console.error('Failed to delete selection');
                }
            } catch (err) {
                console.error('Error deleting selection:', err);
            }
        },

        /**
         * Get count of approved selections
         */
        getApprovedCount() {
            return this.selections.filter(s => s.status === 'approved').length;
        },

        /**
         * Update selection status (approve/reject)
         * @param {number} selId - Selection ID
         * @param {string} status - New status ('approved' or 'rejected')
         */
        async updateSelectionStatus(selId, status) {
            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
                const response = await fetch(`/api/reports/${this.reportId}/selections/${selId}/`, {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ status })
                });

                if (response.ok) {
                    const updated = await response.json();
                    const index = this.selections.findIndex(s => s.id === selId);
                    if (index >= 0) {
                        this.selections[index] = updated;
                    }
                    return true;
                } else {
                    const errorText = await response.text();
                    this.showStatusError('Failed to update status: ' + errorText);
                    return false;
                }
            } catch (err) {
                console.error('Error updating selection status:', err);
                this.showStatusError('Network error: Could not update selection');
                return false;
            }
        },

        /**
         * Approve a YOLO detection
         * @param {number} selId - Selection ID
         */
        async approveSelection(selId) {
            await this.updateSelectionStatus(selId, 'approved');
        },

        /**
         * Reject a YOLO detection
         * @param {number} selId - Selection ID
         */
        async rejectSelection(selId) {
            await this.updateSelectionStatus(selId, 'rejected');
        },

        /**
         * Show error toast for status update failures
         * @param {string} message - Error message
         */
        showStatusError(message) {
            // Remove existing toast
            const existingToast = document.getElementById('status-error-toast');
            if (existingToast) {
                existingToast.remove();
            }

            // Create toast container
            const toast = document.createElement('div');
            toast.id = 'status-error-toast';
            toast.className = 'fixed bottom-4 right-4 bg-red-50 border border-red-200 rounded-lg p-4 shadow-lg z-50 max-w-sm';

            // Create flex container
            const flexContainer = document.createElement('div');
            flexContainer.className = 'flex items-start space-x-3';

            // Create error icon
            const iconSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            iconSvg.setAttribute('class', 'w-5 h-5 text-red-500 flex-shrink-0 mt-0.5');
            iconSvg.setAttribute('fill', 'currentColor');
            iconSvg.setAttribute('viewBox', '0 0 20 20');
            const iconPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            iconPath.setAttribute('fill-rule', 'evenodd');
            iconPath.setAttribute('d', 'M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z');
            iconPath.setAttribute('clip-rule', 'evenodd');
            iconSvg.appendChild(iconPath);

            // Create message container
            const messageDiv = document.createElement('div');
            messageDiv.className = 'flex-1';
            const messageP = document.createElement('p');
            messageP.className = 'text-sm text-red-800';
            messageP.textContent = message;
            messageDiv.appendChild(messageP);

            // Create close button
            const closeBtn = document.createElement('button');
            closeBtn.className = 'text-red-400 hover:text-red-600';
            closeBtn.onclick = () => toast.remove();
            const closeSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            closeSvg.setAttribute('class', 'w-4 h-4');
            closeSvg.setAttribute('fill', 'none');
            closeSvg.setAttribute('stroke', 'currentColor');
            closeSvg.setAttribute('viewBox', '0 0 24 24');
            const closePath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            closePath.setAttribute('stroke-linecap', 'round');
            closePath.setAttribute('stroke-linejoin', 'round');
            closePath.setAttribute('stroke-width', '2');
            closePath.setAttribute('d', 'M6 18L18 6M6 6l12 12');
            closeSvg.appendChild(closePath);
            closeBtn.appendChild(closeSvg);

            // Assemble
            flexContainer.appendChild(iconSvg);
            flexContainer.appendChild(messageDiv);
            flexContainer.appendChild(closeBtn);
            toast.appendChild(flexContainer);
            document.body.appendChild(toast);

            // Auto-dismiss after 5 seconds
            setTimeout(() => {
                if (toast.parentElement) {
                    toast.remove();
                }
            }, 5000);
        },

        /**
         * Check if a selection is a reviewable YOLO detection
         * @param {Object} sel - Selection object
         * @returns {boolean}
         */
        isYoloPending(sel) {
            return sel.source === 'yolo' && sel.status === 'pending';
        },

        /**
         * Trigger extraction of approved selections
         */
        async startExtraction() {
            const approvedCount = this.getApprovedCount();
            if (approvedCount === 0) return;

            this.extracting = true;
            this.extractProgress = { message: 'Starting extraction...', current: 0, total: approvedCount };
            this.extractError = null;
            this.extractTaskId = null;

            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
                const response = await fetch(`/api/reports/${this.reportId}/extract-selections/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    }
                });

                if (!response.ok) {
                    let errorMsg = 'Failed to start extraction';
                    try {
                        const errorData = await response.json();
                        errorMsg = errorData.error || errorMsg;
                        // Sanitize technical error messages
                        if (errorMsg.includes('Traceback') || errorMsg.includes('Exception')) {
                            errorMsg = 'Unable to start extraction. Please try again.';
                        }
                    } catch {
                        // JSON parsing failed, use default message
                    }
                    throw new Error(errorMsg);
                }

                const data = await response.json();
                this.extractTaskId = data.task_id;
                this.extractProgress = { message: 'Extraction queued...', current: 0, total: data.approved_selections };

                // Start polling for task status
                await this.pollTaskStatus(data.task_id);
            } catch (err) {
                console.error('Extraction error:', err);
                this.extractError = err.message || 'Failed to start extraction';
                this.extracting = false;
            }
        },

        /**
         * Poll task status until completion
         * @param {string} taskId - Celery task ID
         */
        async pollTaskStatus(taskId) {
            const pollInterval = 1000; // 1 second
            const maxAttempts = 300; // 5 minutes max
            let attempts = 0;

            while (attempts < maxAttempts) {
                try {
                    const response = await fetch(`/task-status/${taskId}/`);
                    if (!response.ok) {
                        throw new Error('Failed to check task status');
                    }

                    const data = await response.json();

                    if (data.state === 'PROGRESS' && data.progress) {
                        this.extractProgress = {
                            message: data.progress.message || 'Processing...',
                            current: data.progress.current || 0,
                            total: data.progress.total || this.getApprovedCount()
                        };
                    } else if (data.state === 'SUCCESS') {
                        const result = data.result || {};
                        // Handle partial success
                        if (result.failed_pages && result.failed_pages.length > 0) {
                            this.partialSuccess = {
                                tablesExtracted: result.tables_extracted || 0,
                                failedPages: result.failed_pages
                            };
                            this.extractProgress = null;
                            this.extracting = false;
                            // Show partial success modal instead of redirecting immediately
                            return;
                        }
                        this.extractProgress = { message: 'Extraction complete!', current: 100, total: 100 };
                        // Redirect to report detail page after a brief delay
                        setTimeout(() => {
                            window.location.href = `/reports/${this.reportId}/`;
                        }, 1000);
                        return;
                    } else if (data.state === 'FAILURE') {
                        // Sanitize error message for user display
                        let errorMsg = data.error || 'Extraction failed';
                        // Remove technical details if present
                        if (errorMsg.includes('Traceback') || errorMsg.includes('Exception')) {
                            errorMsg = 'Table extraction failed. Please check the PDF and try again.';
                        }
                        throw new Error(errorMsg);
                    }

                    // Wait before next poll
                    await new Promise(resolve => setTimeout(resolve, pollInterval));
                    attempts++;
                } catch (err) {
                    console.error('Polling error:', err);
                    this.extractError = err.message || 'Error checking extraction status';
                    this.extracting = false;
                    return;
                }
            }

            // Timeout
            this.extractError = 'Extraction timed out. Please check the report page.';
            this.extracting = false;
        },

        /**
         * Cancel/close extraction UI (on error)
         */
        closeExtractionError() {
            this.extractError = null;
            this.extracting = false;
            this.extractProgress = null;
        },

        /**
         * Retry extraction after error
         */
        retryExtraction() {
            this.extractError = null;
            this.startExtraction();
        },

        /**
         * Close partial success modal and go to results
         */
        dismissPartialSuccess() {
            this.partialSuccess = null;
            window.location.href = `/reports/${this.reportId}/`;
        },

        /**
         * Check if this is a "zero detections" scenario in review mode
         * @returns {boolean}
         */
        isZeroDetectionsReviewMode() {
            return this.extractionMode === 'review' && this.selections.length === 0;
        },

        /**
         * Get the empty state message based on extraction mode
         * @returns {string}
         */
        getEmptyStateMessage() {
            if (this.extractionMode === 'review') {
                return 'No tables detected. Draw selections manually or try a different PDF.';
            }
            return 'No table selections yet.';
        },

        /**
         * Get the empty state hint based on extraction mode
         * @returns {string}
         */
        getEmptyStateHint() {
            if (this.extractionMode === 'review') {
                return 'You can still draw boxes around tables manually using the "Select Tables" mode.';
            }
            return 'Switch to "Select Tables" mode and draw boxes around tables.';
        }
    };
}

// Make available globally for Alpine.js
window.createBookViewer = createBookViewer;
