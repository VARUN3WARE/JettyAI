# JettyAI Data Scraper and Trust Scorer

This project is a multi-source data scraping pipeline and content trust scoring system. It takes a list of URLs from diverse platforms (Blogs, YouTube, PubMed), extracts the metadata and content, generates topic tags, evaluates the source's credibility to assign a Trust Score, and exports the structured data into JSON files.

## Tools and Libraries Used

- requests: Handles HTTP requests for basic web scraping.
- beautifulsoup4 & lxml: Parses HTML and cleans up the DOM efficiently.
- newspaper3k: Primary library for extracting article text and metadata from blogs.
- pytube & yt-dlp: Used to extract metadata and video information from YouTube.
- youtube-transcript-api: Fetches video captions and transcripts.
- biopython: Interacts with the NCBI Entrez API to fetch reliable PubMed data.
- rake-nltk, nltk, spacy & scikit-learn: Extracts keywords, noun phrases, and generates topic tags using multi-tiered NLP algorithms.
- langdetect: Detects the language of the scraped text.
- tqdm: Provides a visual progress bar in the terminal.

## Scraping Approach

The system uses specific scraping strategies based on the source type:
- Blogs: Attempts to extract clean text using newspaper3k. If that fails or the content is hidden behind complex DOM structures, it falls back to a custom BeautifulSoup parser that aggressively strips away ads, footers, and navigation bars.
- YouTube: Uses youtube-transcript-api to download captions directly. If captions are disabled or inaccessible, the script gracefully falls back to using the video description. yt-dlp handles the metadata extraction.
- PubMed: Uses the BioPython library to query the official Entrez API, ensuring accurate extraction of titles, abstracts, authors, and publication dates without relying on fragile HTML parsing.

## Trust Score Design

The Trust Score evaluates the reliability of a source on a scale from 0.0 to 1.0. It is calculated using the following weighted components:
- Author Credibility (25%): Validates the author's existence and credentials. Verified domains (.gov, .edu) and PubMed authors score higher.
- Citation Score (20%): Evaluates the density of external links and references in the text.
- Domain Authority (20%): Rates the domain reputation. Academic domains score highest, while generic blogs score average.
- Recency Score (20%): Penalizes outdated content. Content older than 5 years receives a heavy penalty.
- Disclaimer Score (15%): For medical content, the presence of a medical disclaimer ("not medical advice") boosts the score to prevent misinformation.

## Limitations

- Paywalls and Captchas: Some websites (like Medium or TowardsDataScience) may meter articles or block automated requests entirely.
- YouTube Subtitles: Auto-generated captions are not always available, and some videos block third-party transcript tools.
- Execution Time: NLP tasks (like keyword extraction) and multiple fallback scraping strategies can increase the execution time per URL.

## How to Run the Project

Follow these steps from start to finish to clone, build, and run the pipeline.

### 1. Clone the Repository
Open your terminal and clone the repository (replace with the actual repository URL):
```bash
git clone https://github.com/VARUN3WARE/JettyAI.git
cd JettyAI
```

### 2. Set Up a Virtual Environment
It is highly recommended to isolate the project dependencies using a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
Install all required Python libraries:
```bash
pip install -r requirements.txt
```

### 4. Prepare Your Input File
Create or modify a file named `urls.txt` in the root directory. Add one URL per line:
```text
# blogs
https://towardsdatascience.com/let-the-ai-do-the-experimenting/
https://towardsdatascience.com/correlation-doesnt-mean-causation-but-what-does-it-mean/
https://www.freecodecamp.org/news/web-scraping-python-tutorial-how-to-scrape-data-from-a-website/

# youtube
https://www.youtube.com/watch?v=uc6-2z4e9oA
https://www.youtube.com/watch?v=ng2o98k983k

# pubmed
https://pubmed.ncbi.nlm.nih.gov/34356119/
```

### 5. Set Up YouTube Cookies (Optional but Recommended)
To scrape restricted YouTube videos or to bypass bot detection, you should provide a `cookies.txt` file in Netscape format.
- Install a browser extension like "Get cookies.txt LOCALLY" for Chrome or Firefox.
- Go to YouTube, log in, and use the extension to export your cookies.
- Save the exported file as `cookies.txt` in the project root folder.

### 6. Run the Scraper
Run the main script, pointing it to your input file and optional cookies file:
```bash
python main.py --input urls.txt --cookies cookies.txt
```

The script will display a progress bar and output the results into the `output/` directory as structured JSON files (`blogs.json`, `youtube.json`, `pubmed.json`, and `scraped_data.json`). It will also print a validation report to the console.
