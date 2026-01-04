import PyPDF2
from PIL import Image
import io
import numpy as np
import re

def is_color_page(page, color_threshold=3, sample_threshold=0.001):
    """
    Determine if a PDF page contains color content.
    
    Args:
        page: PyPDF2 page object
        color_threshold: RGB difference threshold to consider a pixel colored
        sample_threshold: Percentage of colored pixels needed to classify page as colored
    
    Returns:
        bool: True if page is colored, False if monochrome
    """
    has_color = False
    
    try:
        # Check for vector graphics color in page content
        if hasattr(page, 'extract_text') and '/Contents' in page:
            try:
                content = page['/Contents']
                if hasattr(content, 'get_data'):
                    content_data = content.get_data().decode('latin-1', errors='ignore')
                elif isinstance(content, list):
                    content_data = ""
                    for c in content:
                        if hasattr(c, 'get_data'):
                            content_data += c.get_data().decode('latin-1', errors='ignore')
                
                # Look for color commands in PDF content stream
                color_patterns = [
                    r'\b([0-9]*\.?[0-9]+)\s+([0-9]*\.?[0-9]+)\s+([0-9]*\.?[0-9]+)\s+rg',  # RGB color
                    r'\b([0-9]*\.?[0-9]+)\s+([0-9]*\.?[0-9]+)\s+([0-9]*\.?[0-9]+)\s+RG',  # RGB stroke color
                    r'\b([0-9]*\.?[0-9]+)\s+g',  # Gray fill (check if not 0 or 1)
                    r'\b([0-9]*\.?[0-9]+)\s+G',  # Gray stroke
                ]
                
                for pattern in color_patterns:
                    matches = re.findall(pattern, content_data)
                    for match in matches:
                        if len(match) == 3:  # RGB
                            r, g, b = float(match[0]), float(match[1]), float(match[2])
                            if not (r == g == b):  # Not grayscale
                                return True
                        elif len(match) == 1:  # Gray
                            gray_val = float(match[0])
                            # If gray value is not pure black (0) or white (1), it might indicate color usage
                            if 0 < gray_val < 1 and gray_val not in [0.5, 0.25, 0.75]:
                                pass  # This alone doesn't indicate color
            except:
                pass
        
        # Extract images from the page - improved detection
        resources = page.get('/Resources', {})
        if '/XObject' in resources:
            try:
                xObject = resources['/XObject']
                if hasattr(xObject, 'get_object'):
                    xObject = xObject.get_object()
                
                for obj_name in xObject:
                    obj = xObject[obj_name]
                    if hasattr(obj, 'get_object'):
                        obj = obj.get_object()
                    
                    if obj.get('/Subtype') == '/Image':
                        try:
                            # Get image properties
                            width = obj.get('/Width', 0)
                            height = obj.get('/Height', 0)
                            
                            if width == 0 or height == 0:
                                continue
                            
                            # Check color space
                            colorspace = obj.get('/ColorSpace')
                            if colorspace:
                                if isinstance(colorspace, list) and len(colorspace) > 0:
                                    cs_name = str(colorspace[0])
                                else:
                                    cs_name = str(colorspace)
                                
                                # If color space indicates color, mark as colored
                                if any(cs in cs_name for cs in ['RGB', 'Lab', 'DeviceRGB']):
                                    has_color = True
                            
                            # Try to extract and analyze image data
                            try:
                                data = obj.get_data()
                                if data:
                                    img = Image.open(io.BytesIO(data))
                                    
                                    # Convert to RGB if needed
                                    if img.mode in ['RGBA', 'CMYK', 'LAB']:
                                        img = img.convert('RGB')
                                    elif img.mode == 'P':  # Palette mode
                                        img = img.convert('RGB')
                                    
                                    if img.mode == 'RGB':
                                        # More sensitive color detection
                                        img_array = np.array(img)
                                        if len(img_array.shape) == 3 and img_array.shape[2] >= 3:
                                            # Sample image for large images
                                            if img_array.shape[0] * img_array.shape[1] > 1000000:
                                                step = max(1, min(img_array.shape[0], img_array.shape[1]) // 100)
                                                img_array = img_array[::step, ::step]
                                            
                                            r, g, b = img_array[:,:,0], img_array[:,:,1], img_array[:,:,2]
                                            
                                            # Multiple color detection methods
                                            # Method 1: Channel differences
                                            diff_rg = np.abs(r.astype(int) - g.astype(int))
                                            diff_rb = np.abs(r.astype(int) - b.astype(int))
                                            diff_gb = np.abs(g.astype(int) - b.astype(int))
                                            
                                            color_pixels = np.sum((diff_rg > color_threshold) | 
                                                                 (diff_rb > color_threshold) | 
                                                                 (diff_gb > color_threshold))
                                            
                                            total_pixels = img_array.shape[0] * img_array.shape[1]
                                            
                                            if color_pixels / total_pixels > sample_threshold:
                                                return True
                                            
                                            # Method 2: Check for non-grayscale pixels more broadly
                                            is_grayscale = (r == g) & (g == b)
                                            non_grayscale = np.sum(~is_grayscale)
                                            
                                            if non_grayscale / total_pixels > sample_threshold * 0.5:
                                                return True
                                            
                                            # Method 3: Look for specific color ranges (yellows, blues, etc.)
                                            # Yellow-ish colors (like in your example)
                                            yellow_mask = (r > g * 0.8) & (g > b * 1.2) & (r > 100)
                                            yellow_pixels = np.sum(yellow_mask)
                                            
                                            if yellow_pixels / total_pixels > sample_threshold * 0.1:
                                                return True
                                            
                                            # Blue-ish colors
                                            blue_mask = (b > r * 1.2) & (b > g * 1.2) & (b > 100)
                                            blue_pixels = np.sum(blue_mask)
                                            
                                            if blue_pixels / total_pixels > sample_threshold * 0.1:
                                                return True
                                        
                            except Exception as img_error:
                                # If we can't process the image but it has RGB colorspace, assume it might have color
                                if has_color:
                                    return True
                                continue
                                
                        except Exception as obj_error:
                            continue
            except Exception as resource_error:
                pass
                        
    except Exception as e:
        pass
    
    return has_color

def extract_figure_info(page):
    """
    Extract all Figure x-y patterns with captions from a page.
    
    Args:
        page: PyPDF2 page object
    
    Returns:
        list: List of tuples (figure_number, caption) for all figures found
    """
    figures = []
    try:
        # Extract text from the page
        text = page.extract_text()
        if not text:
            return figures
        
        # Pattern to match "Figure x-y" where x is chapter number and y is image number
        # Also captures the caption that follows
        figure_pattern = r'Figure\s+(\d+)-(\d+)\.?\s*([^\n\r]*)'
        
        matches = re.findall(figure_pattern, text, re.IGNORECASE)
        
        # Extract figure information for all matches with captions
        for match in matches:
            chapter_num, image_num, caption = match
            # Clean up caption text
            caption = caption.strip()
            if caption:
                # Remove any trailing periods or extra whitespace
                caption = caption.rstrip('.')
                figure_number = f"{chapter_num}-{image_num}"
                figures.append((figure_number, caption))
        
        return figures
        
    except Exception as e:
        return figures

def has_figure_pattern(page):
    """
    Check if a page contains Figure x-y pattern with caption.
    
    Args:
        page: PyPDF2 page object
    
    Returns:
        bool: True if page contains Figure x-y pattern, False otherwise
    """
    figures = extract_figure_info(page)
    return len(figures) > 0

def find_figure_pages(pdf_path, output_file='figure_pages.txt', page_offset=33):
    """
    Identify all pages containing Figure x-y patterns with captions in a PDF document.
    Creates a detailed output file with figure information and page numbers.
    
    Args:
        pdf_path: Path to the PDF file
        output_file: Path to save the results
        page_offset: Number of pages to subtract for book page numbering (default 33)
    
    Returns:
        list: Page numbers of pages with Figure patterns (book page numbering)
    """
    figure_pages = []
    all_figures = []
    
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            total_pages = len(pdf_reader.pages)
            
            print(f"Analyzing {total_pages} pages...")
            
            for page_num in range(total_pages):
                page = pdf_reader.pages[page_num]
                pdf_page_num = page_num + 1  # PDF page number (1-indexed)
                book_page_num = pdf_page_num - page_offset  # Book page number
                
                # Extract figure information from the page
                figures_on_page = extract_figure_info(page)
                
                if figures_on_page:
                    figure_pages.append(book_page_num)
                    for figure_number, caption in figures_on_page:
                        all_figures.append({
                            'figure_number': figure_number,
                            'caption': caption,
                            'pdf_page': pdf_page_num,
                            'book_page': book_page_num
                        })
                    
                    if book_page_num > 0:  # Only show positive book page numbers
                        print(f"PDF Page {pdf_page_num} (Book Page {book_page_num}): HAS {len(figures_on_page)} FIGURE(S)")
                    else:
                        print(f"PDF Page {pdf_page_num} (Front Matter): HAS {len(figures_on_page)} FIGURE(S)")
                
                # Progress indicator
                if (page_num + 1) % 50 == 0:
                    print(f"Progress: {page_num + 1}/{total_pages} pages processed")
        
        # Filter figures by book vs front matter
        book_figures = [fig for fig in all_figures if fig['book_page'] > 0]
        front_matter_figures = [fig for fig in all_figures if fig['book_page'] <= 0]
        
        # Save detailed results to file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"Figure Analysis Report\n")
            f.write(f"=====================\n\n")
            f.write(f"Total PDF pages analyzed: {total_pages}\n")
            f.write(f"Page offset applied: {page_offset} (PDF page {page_offset + 1} = Book page 1)\n")
            f.write(f"Total figures found: {len(all_figures)}\n")
            f.write(f"Figures in book content: {len(book_figures)}\n")
            f.write(f"Figures in front matter: {len(front_matter_figures)}\n\n")
            
            f.write("Detailed Figure Information:\n")
            f.write("===========================\n\n")
            
            # Sort figures by figure number (chapter-number)
            def sort_key(fig):
                parts = fig['figure_number'].split('-')
                return (int(parts[0]), int(parts[1]))
            
            sorted_figures = sorted(book_figures, key=sort_key)
            
            for fig in sorted_figures:
                f.write(f"Figure {fig['figure_number']}. {fig['caption']} on page number: {fig['pdf_page']}. ")
                f.write(f"This includes an offset of {page_offset}. ")
                f.write(f"That is this Figure {fig['figure_number']} is present on page number {fig['book_page']} ({fig['pdf_page']} of {total_pages})\n\n")
            
            if front_matter_figures:
                f.write("\nFigures in Front Matter:\n")
                f.write("========================\n\n")
                for fig in front_matter_figures:
                    f.write(f"Figure {fig['figure_number']}. {fig['caption']} on PDF page: {fig['pdf_page']}\n\n")
        
        print(f"\nAnalysis complete!")
        print(f"Total figures found: {len(all_figures)}")
        print(f"Book content figures: {len(book_figures)}")
        print(f"Front matter figures: {len(front_matter_figures)}")
        print(f"Results saved to: {output_file}")
        
        return [fig['book_page'] for fig in book_figures]
        
    except Exception as e:
        print(f"Error processing PDF: {e}")
        return []

# Usage
if __name__ == "__main__":
    pdf_path = "hmlpy.pdf"  # Replace with your PDF path
    figure_pages = find_figure_pages(pdf_path)
    
    print(f"\nPages with Figure x-y patterns: {figure_pages}")