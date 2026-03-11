/**
 * Bounding Box Manager
 *
 * Canvas overlay component for displaying and drawing table selections.
 * Handles coordinate conversion between canvas (top-left origin) and PDF (bottom-left origin) space.
 */

/**
 * Create SVG element safely
 */
function createSvgIcon(pathD, size = 16) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('stroke-linecap', 'round');
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('d', pathD);

    svg.appendChild(path);
    return svg;
}

/**
 * Create filled SVG icon for error messages
 */
function createFilledSvgIcon(pathD, fillRule = 'evenodd') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', '20');
    svg.setAttribute('height', '20');
    svg.setAttribute('viewBox', '0 0 20 20');
    svg.setAttribute('fill', 'currentColor');
    svg.style.flexShrink = '0';
    svg.style.marginTop = '2px';

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('fill-rule', fillRule);
    path.setAttribute('d', pathD);
    path.setAttribute('clip-rule', fillRule);

    svg.appendChild(path);
    return svg;
}

export class BoundingBoxManager {
    constructor(config) {
        this.reportId = config.reportId;
        this.onSelectionChange = config.onSelectionChange || (() => {});
        this.onError = config.onError || ((msg) => console.error(msg));

        // Selection state
        this.selections = [];
        this.selectedBoxId = null;
        this.pendingBox = null; // Box being drawn, not yet saved

        // Drawing state
        this.isDrawing = false;
        this.drawStartX = 0;
        this.drawStartY = 0;
        this.drawCurrentX = 0;
        this.drawCurrentY = 0;
        this.activeOverlay = null;

        // Overlay canvases keyed by page container id
        this.overlays = {};

        // Confirm/cancel UI element
        this.confirmPopup = null;

        // Error toast state
        this.errorToast = null;
        this.pendingRetryData = null;

        // Bind keyboard handler
        this._handleKeydown = this._handleKeydown.bind(this);
        document.addEventListener('keydown', this._handleKeydown);
    }

    /**
     * Get CSRF token from meta tag
     */
    getCSRFToken() {
        return document.querySelector('meta[name="csrf-token"]')?.content || '';
    }

    /**
     * Convert canvas coordinates to PDF coordinates
     * PDF uses bottom-left origin, canvas uses top-left
     * @param {number} canvasX - X coordinate in canvas pixels
     * @param {number} canvasY - Y coordinate in canvas pixels
     * @param {HTMLCanvasElement} pdfCanvas - The PDF canvas element
     * @returns {{x: number, y: number}} PDF coordinates
     */
    canvasToPdf(canvasX, canvasY, pdfCanvas) {
        const scale = parseFloat(pdfCanvas.dataset.scale) || 1.5;
        const pdfHeight = parseFloat(pdfCanvas.dataset.pdfHeight);

        // Canvas to PDF: divide by scale, then flip Y axis
        const pdfX = canvasX / scale;
        const pdfY = pdfHeight - (canvasY / scale);

        return { x: pdfX, y: pdfY };
    }

    /**
     * Convert PDF coordinates to canvas coordinates
     * @param {number} pdfX - X coordinate in PDF space
     * @param {number} pdfY - Y coordinate in PDF space
     * @param {HTMLCanvasElement} pdfCanvas - The PDF canvas element
     * @returns {{x: number, y: number}} Canvas coordinates
     */
    pdfToCanvas(pdfX, pdfY, pdfCanvas) {
        const scale = parseFloat(pdfCanvas.dataset.scale) || 1.5;
        const pdfHeight = parseFloat(pdfCanvas.dataset.pdfHeight);

        // PDF to canvas: flip Y axis first, then multiply by scale
        const canvasX = pdfX * scale;
        const canvasY = (pdfHeight - pdfY) * scale;

        return { x: canvasX, y: canvasY };
    }

    /**
     * Get box color based on source and status
     * @param {Object} selection
     * @returns {string} CSS color
     */
    getBoxColor(selection) {
        if (selection.source === 'manual') {
            return '#3B82F6'; // Blue for manual
        }
        if (selection.status === 'approved') {
            return '#10B981'; // Green for approved
        }
        if (selection.status === 'pending') {
            return '#F59E0B'; // Orange for YOLO pending
        }
        if (selection.status === 'rejected') {
            return 'rgba(239, 68, 68, 0.5)'; // Faded red for rejected
        }
        return '#6B7280'; // Gray fallback
    }

    /**
     * Create overlay canvas for a page container
     * @param {string} containerId - ID of the page container (e.g., 'left-page-container')
     * @param {number} pageNum - Page number this overlay is for
     */
    createOverlay(containerId, pageNum) {
        const container = document.getElementById(containerId);
        const pdfCanvas = container?.querySelector('canvas');

        if (!container || !pdfCanvas || pdfCanvas.width === 0) {
            return null;
        }

        // Remove existing overlay if any
        this.removeOverlay(containerId);

        // Create overlay canvas
        const overlay = document.createElement('canvas');
        overlay.id = `${containerId}-overlay`;
        overlay.className = 'bbox-overlay';
        overlay.width = pdfCanvas.width;
        overlay.height = pdfCanvas.height;
        overlay.dataset.pageNum = pageNum;
        overlay.dataset.containerId = containerId;

        // Position absolutely over PDF canvas
        overlay.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            pointer-events: auto;
            cursor: crosshair;
        `;

        // Store reference to PDF canvas
        overlay.pdfCanvas = pdfCanvas;

        // Ensure container is positioned
        if (getComputedStyle(container).position === 'static') {
            container.style.position = 'relative';
        }

        container.appendChild(overlay);
        this.overlays[containerId] = overlay;

        // Attach mouse events
        overlay.addEventListener('mousedown', (e) => this._onMouseDown(e, overlay));
        overlay.addEventListener('mousemove', (e) => this._onMouseMove(e, overlay));
        overlay.addEventListener('mouseup', (e) => this._onMouseUp(e, overlay));
        overlay.addEventListener('click', (e) => this._onClick(e, overlay));

        // Render existing selections
        this.render(containerId);

        return overlay;
    }

    /**
     * Remove overlay canvas
     * @param {string} containerId
     */
    removeOverlay(containerId) {
        const existing = this.overlays[containerId];
        if (existing) {
            existing.remove();
            delete this.overlays[containerId];
        }
    }

    /**
     * Load selections from API
     * @param {number[]} pageNums - Optional array of page numbers to filter
     */
    async loadSelections(pageNums = null) {
        try {
            let url = `/api/reports/${this.reportId}/selections/`;
            if (pageNums && pageNums.length > 0) {
                // Load for specific pages
                const params = new URLSearchParams();
                pageNums.forEach(p => params.append('page_num', p));
                url += '?' + params.toString();
            }

            const response = await fetch(url, {
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            if (response.ok) {
                const data = await response.json();
                if (pageNums) {
                    // Merge with existing selections for other pages
                    const otherPageSelections = this.selections.filter(
                        s => !pageNums.includes(s.page_num)
                    );
                    this.selections = [...otherPageSelections, ...data];
                } else {
                    this.selections = data;
                }
                this.onSelectionChange(this.selections);
                this.renderAll();
            }
        } catch (err) {
            console.error('Error loading selections:', err);
        }
    }

    /**
     * Render selections on a specific overlay
     * @param {string} containerId
     */
    render(containerId) {
        const overlay = this.overlays[containerId];
        if (!overlay || !overlay.pdfCanvas) return;

        const ctx = overlay.getContext('2d');
        const pageNum = parseInt(overlay.dataset.pageNum);
        const pdfCanvas = overlay.pdfCanvas;

        // Clear canvas
        ctx.clearRect(0, 0, overlay.width, overlay.height);

        // Draw existing selections for this page
        const pageSelections = this.selections.filter(s => s.page_num === pageNum);

        for (const sel of pageSelections) {
            this._drawBox(ctx, sel, pdfCanvas, sel.id === this.selectedBoxId);
        }

        // Draw pending box if on this page
        if (this.pendingBox && this.pendingBox.containerId === containerId) {
            this._drawPendingBox(ctx);
        }

        // Draw current drawing rectangle
        if (this.isDrawing && this.activeOverlay === overlay) {
            this._drawDrawingRect(ctx);
        }
    }

    /**
     * Render all overlays
     */
    renderAll() {
        for (const containerId of Object.keys(this.overlays)) {
            this.render(containerId);
        }
    }

    /**
     * Draw a selection box
     */
    _drawBox(ctx, selection, pdfCanvas, isSelected) {
        // Convert PDF coords to canvas coords
        // Note: In PDF space, y1 > y2 for a box (y1 is top, y2 is bottom)
        // After conversion, we need to draw from min to max
        const topLeft = this.pdfToCanvas(selection.x1, selection.y1, pdfCanvas);
        const bottomRight = this.pdfToCanvas(selection.x2, selection.y2, pdfCanvas);

        const x = Math.min(topLeft.x, bottomRight.x);
        const y = Math.min(topLeft.y, bottomRight.y);
        const width = Math.abs(bottomRight.x - topLeft.x);
        const height = Math.abs(bottomRight.y - topLeft.y);

        const color = this.getBoxColor(selection);

        // Fill - convert hex to rgba
        if (color.startsWith('#')) {
            const r = parseInt(color.slice(1, 3), 16);
            const g = parseInt(color.slice(3, 5), 16);
            const b = parseInt(color.slice(5, 7), 16);
            ctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.15)`;
        } else if (color.startsWith('rgba')) {
            // Already rgba with some alpha, just use it with lower opacity
            ctx.fillStyle = color;
        } else {
            ctx.fillStyle = 'rgba(107, 114, 128, 0.15)';
        }
        ctx.fillRect(x, y, width, height);

        // Border
        ctx.strokeStyle = color;
        ctx.lineWidth = isSelected ? 3 : 2;
        ctx.setLineDash([]);
        ctx.strokeRect(x, y, width, height);

        // Selection highlight
        if (isSelected) {
            ctx.strokeStyle = '#1D4ED8';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.strokeRect(x - 2, y - 2, width + 4, height + 4);
            ctx.setLineDash([]);
        }
    }

    /**
     * Draw pending box (not yet saved)
     */
    _drawPendingBox(ctx) {
        const box = this.pendingBox;
        ctx.fillStyle = 'rgba(59, 130, 246, 0.2)';
        ctx.fillRect(box.x, box.y, box.width, box.height);
        ctx.strokeStyle = '#3B82F6';
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 3]);
        ctx.strokeRect(box.x, box.y, box.width, box.height);
        ctx.setLineDash([]);
    }

    /**
     * Draw rectangle being drawn
     */
    _drawDrawingRect(ctx) {
        const x = Math.min(this.drawStartX, this.drawCurrentX);
        const y = Math.min(this.drawStartY, this.drawCurrentY);
        const width = Math.abs(this.drawCurrentX - this.drawStartX);
        const height = Math.abs(this.drawCurrentY - this.drawStartY);

        ctx.fillStyle = 'rgba(59, 130, 246, 0.1)';
        ctx.fillRect(x, y, width, height);
        ctx.strokeStyle = '#3B82F6';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 2]);
        ctx.strokeRect(x, y, width, height);
        ctx.setLineDash([]);
    }

    /**
     * Mouse down - start drawing
     */
    _onMouseDown(e, overlay) {
        if (this.pendingBox) return; // Don't start new drawing while pending exists

        const rect = overlay.getBoundingClientRect();
        this.isDrawing = true;
        this.activeOverlay = overlay;
        this.drawStartX = e.clientX - rect.left;
        this.drawStartY = e.clientY - rect.top;
        this.drawCurrentX = this.drawStartX;
        this.drawCurrentY = this.drawStartY;
    }

    /**
     * Mouse move - update drawing
     */
    _onMouseMove(e, overlay) {
        if (!this.isDrawing || this.activeOverlay !== overlay) return;

        const rect = overlay.getBoundingClientRect();
        this.drawCurrentX = Math.max(0, Math.min(e.clientX - rect.left, overlay.width));
        this.drawCurrentY = Math.max(0, Math.min(e.clientY - rect.top, overlay.height));

        this.render(overlay.dataset.containerId);
    }

    /**
     * Mouse up - finish drawing
     */
    _onMouseUp(e, overlay) {
        if (!this.isDrawing || this.activeOverlay !== overlay) return;

        this.isDrawing = false;
        this.activeOverlay = null;

        const width = Math.abs(this.drawCurrentX - this.drawStartX);
        const height = Math.abs(this.drawCurrentY - this.drawStartY);

        // Ignore boxes smaller than 20x20 canvas pixels (accidental clicks)
        if (width < 20 || height < 20) {
            this.render(overlay.dataset.containerId);
            return;
        }

        // Create pending box
        const x = Math.min(this.drawStartX, this.drawCurrentX);
        const y = Math.min(this.drawStartY, this.drawCurrentY);

        this.pendingBox = {
            x,
            y,
            width,
            height,
            containerId: overlay.dataset.containerId,
            pageNum: parseInt(overlay.dataset.pageNum),
            overlay
        };

        this.render(overlay.dataset.containerId);
        this._showConfirmPopup(overlay);
    }

    /**
     * Click handler - select existing box
     */
    _onClick(e, overlay) {
        if (this.isDrawing || this.pendingBox) return;

        const rect = overlay.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;
        const pageNum = parseInt(overlay.dataset.pageNum);
        const pdfCanvas = overlay.pdfCanvas;

        // Find clicked box
        const pageSelections = this.selections.filter(s => s.page_num === pageNum);
        let clickedBox = null;

        for (const sel of pageSelections) {
            const topLeft = this.pdfToCanvas(sel.x1, sel.y1, pdfCanvas);
            const bottomRight = this.pdfToCanvas(sel.x2, sel.y2, pdfCanvas);

            const boxX = Math.min(topLeft.x, bottomRight.x);
            const boxY = Math.min(topLeft.y, bottomRight.y);
            const boxWidth = Math.abs(bottomRight.x - topLeft.x);
            const boxHeight = Math.abs(bottomRight.y - topLeft.y);

            if (clickX >= boxX && clickX <= boxX + boxWidth &&
                clickY >= boxY && clickY <= boxY + boxHeight) {
                clickedBox = sel;
                break;
            }
        }

        // Update selection
        const prevSelected = this.selectedBoxId;
        this.selectedBoxId = clickedBox ? clickedBox.id : null;

        if (prevSelected !== this.selectedBoxId) {
            this.renderAll();
            this.onSelectionChange(this.selections, this.selectedBoxId);
        }
    }

    /**
     * Show confirm/cancel popup near the pending box
     */
    _showConfirmPopup(overlay) {
        this._hideConfirmPopup();

        const container = document.getElementById(this.pendingBox.containerId);

        this.confirmPopup = document.createElement('div');
        this.confirmPopup.className = 'bbox-confirm-popup';
        this.confirmPopup.style.cssText = `
            position: absolute;
            top: ${this.pendingBox.y + this.pendingBox.height + 8}px;
            left: ${this.pendingBox.x}px;
            background: white;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 8px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            display: flex;
            gap: 8px;
            z-index: 100;
        `;

        // Confirm button
        const confirmBtn = document.createElement('button');
        confirmBtn.appendChild(createSvgIcon('M5 13l4 4L19 7'));
        const confirmText = document.createElement('span');
        confirmText.textContent = 'Save';
        confirmBtn.appendChild(confirmText);
        confirmBtn.style.cssText = `
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 6px 12px;
            background: #10B981;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            cursor: pointer;
        `;
        confirmBtn.onclick = () => this._confirmPendingBox();

        // Cancel button
        const cancelBtn = document.createElement('button');
        cancelBtn.appendChild(createSvgIcon('M6 18L18 6M6 6l12 12'));
        const cancelText = document.createElement('span');
        cancelText.textContent = 'Cancel';
        cancelBtn.appendChild(cancelText);
        cancelBtn.style.cssText = `
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 6px 12px;
            background: #EF4444;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 14px;
            cursor: pointer;
        `;
        cancelBtn.onclick = () => this._cancelPendingBox();

        this.confirmPopup.appendChild(confirmBtn);
        this.confirmPopup.appendChild(cancelBtn);
        container.appendChild(this.confirmPopup);
    }

    /**
     * Hide confirm popup
     */
    _hideConfirmPopup() {
        if (this.confirmPopup) {
            this.confirmPopup.remove();
            this.confirmPopup = null;
        }
    }

    /**
     * Confirm and save pending box
     */
    async _confirmPendingBox() {
        if (!this.pendingBox) return;

        const box = this.pendingBox;
        const pdfCanvas = box.overlay.pdfCanvas;

        // Convert canvas coordinates to PDF coordinates
        const topLeft = this.canvasToPdf(box.x, box.y, pdfCanvas);
        const bottomRight = this.canvasToPdf(box.x + box.width, box.y + box.height, pdfCanvas);

        // In PDF space, x1 < x2 and y1 > y2 (y1 is top, y2 is bottom due to Y-flip)
        const selectionData = {
            page_num: box.pageNum,
            x1: Math.min(topLeft.x, bottomRight.x),
            y1: Math.max(topLeft.y, bottomRight.y), // Higher Y in PDF = top
            x2: Math.max(topLeft.x, bottomRight.x),
            y2: Math.min(topLeft.y, bottomRight.y), // Lower Y in PDF = bottom
            source: 'manual'
        };

        this._hideConfirmPopup();

        try {
            const response = await fetch(`/api/reports/${this.reportId}/selections/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(selectionData)
            });

            if (response.ok) {
                const newSelection = await response.json();
                this.selections.push(newSelection);
                this.pendingBox = null;
                this.onSelectionChange(this.selections);
                this.renderAll();
            } else {
                const errorText = await response.text();
                this.pendingRetryData = { box, selectionData };
                this._showErrorToast('Failed to save selection: ' + errorText);
            }
        } catch (err) {
            console.error('Error saving selection:', err);
            this.pendingRetryData = { box, selectionData };
            this._showErrorToast('Network error: Could not save selection');
        }
    }

    /**
     * Cancel pending box
     */
    _cancelPendingBox() {
        if (!this.pendingBox) return;

        const containerId = this.pendingBox.containerId;
        this.pendingBox = null;
        this._hideConfirmPopup();
        this.render(containerId);
    }

    /**
     * Handle keyboard events
     */
    _handleKeydown(e) {
        if (e.key === 'Escape') {
            if (this.pendingBox) {
                this._cancelPendingBox();
                e.preventDefault();
            } else if (this.selectedBoxId) {
                this.selectedBoxId = null;
                this.renderAll();
                this.onSelectionChange(this.selections, null);
            }
        }
    }

    /**
     * Show error toast with retry option
     */
    _showErrorToast(message) {
        this._hideErrorToast();

        this.errorToast = document.createElement('div');
        this.errorToast.className = 'bbox-error-toast';
        this.errorToast.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #FEF2F2;
            border: 1px solid #FCA5A5;
            border-radius: 8px;
            padding: 16px;
            max-width: 400px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 12px;
        `;

        const messageEl = document.createElement('div');
        messageEl.style.cssText = `
            display: flex;
            align-items: flex-start;
            gap: 12px;
            color: #991B1B;
        `;

        // Error icon
        const errorIconPath = 'M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z';
        messageEl.appendChild(createFilledSvgIcon(errorIconPath));

        const messageText = document.createElement('span');
        messageText.textContent = message;
        messageEl.appendChild(messageText);

        const buttonContainer = document.createElement('div');
        buttonContainer.style.cssText = `
            display: flex;
            justify-content: flex-end;
            gap: 8px;
        `;

        // Retry button
        if (this.pendingRetryData) {
            const retryBtn = document.createElement('button');
            retryBtn.textContent = 'Retry';
            retryBtn.style.cssText = `
                padding: 6px 12px;
                background: #DC2626;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
                cursor: pointer;
            `;
            retryBtn.onclick = () => this._retryPendingSave();
            buttonContainer.appendChild(retryBtn);
        }

        // Dismiss button
        const dismissBtn = document.createElement('button');
        dismissBtn.textContent = 'Dismiss';
        dismissBtn.style.cssText = `
            padding: 6px 12px;
            background: #F3F4F6;
            color: #374151;
            border: 1px solid #D1D5DB;
            border-radius: 4px;
            font-size: 14px;
            cursor: pointer;
        `;
        dismissBtn.onclick = () => {
            this._hideErrorToast();
            // Clear pending box on dismiss
            if (this.pendingBox) {
                const containerId = this.pendingBox.containerId;
                this.pendingBox = null;
                this.render(containerId);
            }
            this.pendingRetryData = null;
        };
        buttonContainer.appendChild(dismissBtn);

        this.errorToast.appendChild(messageEl);
        this.errorToast.appendChild(buttonContainer);
        document.body.appendChild(this.errorToast);
    }

    /**
     * Hide error toast
     */
    _hideErrorToast() {
        if (this.errorToast) {
            this.errorToast.remove();
            this.errorToast = null;
        }
    }

    /**
     * Retry pending save after error
     */
    async _retryPendingSave() {
        if (!this.pendingRetryData) return;

        const { box, selectionData } = this.pendingRetryData;
        this._hideErrorToast();

        try {
            const response = await fetch(`/api/reports/${this.reportId}/selections/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify(selectionData)
            });

            if (response.ok) {
                const newSelection = await response.json();
                this.selections.push(newSelection);
                this.pendingBox = null;
                this.pendingRetryData = null;
                this.onSelectionChange(this.selections);
                this.renderAll();
            } else {
                const errorText = await response.text();
                this._showErrorToast('Failed to save selection: ' + errorText);
            }
        } catch (err) {
            console.error('Error saving selection:', err);
            this._showErrorToast('Network error: Could not save selection');
        }
    }

    /**
     * Update selection status (for YOLO approve/reject)
     */
    async updateStatus(selectionId, status) {
        try {
            const response = await fetch(`/api/reports/${this.reportId}/selections/${selectionId}/`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({ status })
            });

            if (response.ok) {
                const updated = await response.json();
                const index = this.selections.findIndex(s => s.id === selectionId);
                if (index >= 0) {
                    this.selections[index] = updated;
                }
                this.onSelectionChange(this.selections);
                this.renderAll();
                return true;
            } else {
                const errorText = await response.text();
                this.onError('Failed to update selection: ' + errorText);
                return false;
            }
        } catch (err) {
            console.error('Error updating selection:', err);
            this.onError('Network error: Could not update selection');
            return false;
        }
    }

    /**
     * Delete a selection
     */
    async deleteSelection(selectionId) {
        try {
            const response = await fetch(`/api/reports/${this.reportId}/selections/${selectionId}/`, {
                method: 'DELETE',
                headers: {
                    'X-CSRFToken': this.getCSRFToken()
                }
            });

            if (response.ok) {
                this.selections = this.selections.filter(s => s.id !== selectionId);
                if (this.selectedBoxId === selectionId) {
                    this.selectedBoxId = null;
                }
                this.onSelectionChange(this.selections);
                this.renderAll();
                return true;
            } else {
                this.onError('Failed to delete selection');
                return false;
            }
        } catch (err) {
            console.error('Error deleting selection:', err);
            this.onError('Network error: Could not delete selection');
            return false;
        }
    }

    /**
     * Get currently selected box
     */
    getSelectedBox() {
        if (!this.selectedBoxId) return null;
        return this.selections.find(s => s.id === this.selectedBoxId);
    }

    /**
     * Select a box by ID
     */
    selectBox(boxId) {
        this.selectedBoxId = boxId;
        this.renderAll();
        this.onSelectionChange(this.selections, this.selectedBoxId);
    }

    /**
     * Clear selection
     */
    clearSelection() {
        this.selectedBoxId = null;
        this.renderAll();
        this.onSelectionChange(this.selections, null);
    }

    /**
     * Cleanup - remove event listeners and overlays
     */
    destroy() {
        document.removeEventListener('keydown', this._handleKeydown);
        this._hideConfirmPopup();
        this._hideErrorToast();

        for (const containerId of Object.keys(this.overlays)) {
            this.removeOverlay(containerId);
        }
    }
}

// Export for ES modules and make available globally
window.BoundingBoxManager = BoundingBoxManager;
