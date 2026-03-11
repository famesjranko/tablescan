/**
 * Book Viewer Alpine.js Component
 *
 * PDF rendering and navigation for book-style spread layout.
 * Uses PDF.js for rendering and provides zoom, navigation, and selection features.
 */

import * as pdfjsLib from 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.min.mjs';

pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.4.168/build/pdf.worker.min.mjs';

export function createBookViewer(config) {
    return {
        // Configuration
        reportId: config.reportId,
        pdfUrl: config.pdfUrl,

        // PDF state
        pdfDoc: null,
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
        error: null,
        renderError: null,

        // Page input for direct navigation
        gotoPageInput: '',

        // Selection state
        selections: [],
        isDrawing: false,
        drawingPage: null,
        startX: 0,
        startY: 0,
        currentX: 0,
        currentY: 0,

        /**
         * Initialize the viewer - load PDF and selections
         */
        async init() {
            try {
                this.loading = true;
                this.error = null;

                // Load the PDF document
                const loadingTask = pdfjsLib.getDocument(this.pdfUrl);
                this.pdfDoc = await loadingTask.promise;
                this.totalPages = this.pdfDoc.numPages;
                this.gotoPageInput = '1';

                // Load page metadata (dimensions for all pages)
                await this.loadPageMetadata();

                // Load existing selections from API
                await this.loadSelections();

                // Render the first spread
                await this.renderSpread();

                this.loading = false;
            } catch (err) {
                console.error('Error loading PDF:', err);
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
                    const page = await this.pdfDoc.getPage(i);
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
            this.leftPageNum = this.currentSpread * 2 + 1;
            this.rightPageNum = this.currentSpread * 2 + 2;
            this.renderError = null;
            this.renderingPages = true;

            try {
                // Render left page
                await this.renderPage(this.leftPageNum, 'left-page-canvas');

                // Render right page if it exists
                if (this.rightPageNum <= this.totalPages) {
                    await this.renderPage(this.rightPageNum, 'right-page-canvas');
                } else {
                    // Clear right canvas for single page or odd page count
                    this.clearCanvas('right-page-canvas');
                }
            } catch (err) {
                console.error('Error rendering spread:', err);
                this.renderError = err.message || 'Failed to render pages';
            } finally {
                this.renderingPages = false;
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

            try {
                const page = await this.pdfDoc.getPage(pageNum);
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

                await page.render({
                    canvasContext: ctx,
                    viewport: viewport
                }).promise;
            } catch (err) {
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
         * Navigate to a specific page (internal method)
         */
        goToPage(pageNum) {
            if (pageNum < 1 || pageNum > this.totalPages) return;
            this.currentSpread = Math.floor((pageNum - 1) / 2);
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
         * Calculate selection box style for overlay
         */
        getSelectionStyle(sel, side) {
            const container = document.getElementById(`${side}-page-container`);
            const canvas = document.getElementById(`${side}-page-canvas`);
            if (!container || !canvas || canvas.width === 0) {
                return { display: 'none' };
            }

            // Scale coordinates from percentage to canvas pixels
            const scaleX = canvas.width / 100;
            const scaleY = canvas.height / 100;

            return {
                left: (sel.x1 * scaleX) + 'px',
                top: (sel.y1 * scaleY) + 'px',
                width: ((sel.x2 - sel.x1) * scaleX) + 'px',
                height: ((sel.y2 - sel.y1) * scaleY) + 'px'
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

            const rect = canvas.getBoundingClientRect();
            this.currentX = Math.max(0, Math.min(event.clientX - rect.left, canvas.width));
            this.currentY = Math.max(0, Math.min(event.clientY - rect.top, canvas.height));
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
            const x1 = Math.min(this.startX, this.currentX) / canvas.width * 100;
            const y1 = Math.min(this.startY, this.currentY) / canvas.height * 100;
            const x2 = Math.max(this.startX, this.currentX) / canvas.width * 100;
            const y2 = Math.max(this.startY, this.currentY) / canvas.height * 100;

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
        }
    };
}

// Make available globally for Alpine.js
window.createBookViewer = createBookViewer;
