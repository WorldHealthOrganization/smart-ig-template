document.addEventListener("DOMContentLoaded", function() {
  let db;
  const dbName = 'searchDB';
  const storeName = 'searchIndex';
  const searchButton = document.getElementById('search-button');
  const searchBox = document.getElementById('search-box');
  const searchResults = document.getElementById('search-results');

  // Open IndexedDB
  const request = indexedDB.open(dbName, 1);

  request.onupgradeneeded = function(event) {
    db = event.target.result;
    const objectStore = db.createObjectStore(storeName, { keyPath: 'url' });
    objectStore.createIndex('content', 'content', { unique: false });
  };

  request.onsuccess = function(event) {
    db = event.target.result;
    loadDataToIndexedDB();
  };

  request.onerror = function(event) {
    console.error('Database error:', event.target.errorCode);
  };

  function loadDataToIndexedDB() {
    fetch('assets/js/searchIndex.json')
      .then(response => {
        if (!response.ok) {
          throw new Error('Network response was not ok');
        }
        return response.json();
      })
      .then(searchIndex => {
        console.log('Search index loaded:', searchIndex);
        const transaction = db.transaction([storeName], 'readwrite');
        const objectStore = transaction.objectStore(storeName);
        searchIndex.forEach(function(doc) {
          objectStore.add(doc);
        });
        console.log('Data loaded into IndexedDB');
      })
      .catch(error => console.error('Error fetching the search index:', error));
  }

  searchButton.addEventListener('click', function() {
    searchBox.classList.toggle('visible');
    if (searchBox.classList.contains('visible')) {
      searchBox.focus();
    } else {
      searchBox.blur();
      searchResults.innerHTML = ''; // Clear results when search box is hidden
      searchResults.style.display = 'none'; // Hide results when search box is hidden
    }
  });

  searchBox.addEventListener('input', function(event) {
    const query = event.target.value.trim();
    console.log('Search query:', query);

    if (query.length > 2) {
      performSearch(query);
    } else {
      searchResults.innerHTML = ''; // Clear results for queries less than 3 characters
      searchResults.style.display = 'none'; // Hide results when query is too short
    }
  });

  function performSearch(query) {
    const transaction = db.transaction([storeName], 'readonly');
    const objectStore = transaction.objectStore(storeName);
    const index = objectStore.index('content');
    const results = [];
    const cursorRequest = index.openCursor();

    cursorRequest.onsuccess = function(event) {
      const cursor = event.target.result;
      if (cursor) {
        if (cursor.value.content.toLowerCase().includes(query.toLowerCase())) {
          results.push(cursor.value);
        }
        cursor.continue();
      } else {
        displayResults(results, query);
      }
    };

    cursorRequest.onerror = function(event) {
      console.error('Cursor error:', event.target.errorCode);
    };
  }

  function displayResults(results, query) {
    searchResults.innerHTML = '';
    searchResults.style.display = 'block'; // Ensure results are visible
    if (results.length) {
      results.forEach(item => {
        console.log('Displaying result item:', item);
        const snippet = generateSnippet(item.content, query);
        const relativeUrl = item.url.startsWith('/') ? `.${item.url}` : item.url;
        const displayUrl = relativeUrl.startsWith('./') ? relativeUrl.slice(2) : relativeUrl; // Remove ./ for display
        const resultItem = document.createElement('li');
        resultItem.innerHTML = `<a href="${relativeUrl}" class="filename">${item.title || displayUrl}</a><a href="${relativeUrl}" class="snippet">${snippet}</a>`;
        searchResults.appendChild(resultItem);
      });
    } else {
      searchResults.innerHTML = '<li>No results found</li>';
    }
  }

  function generateSnippet(content, query) {
    const start = content.toLowerCase().indexOf(query.toLowerCase());
    if (start === -1) {
      return content.substring(0, 100); // Default to first 100 characters if query not found
    }
    const end = start + 100 > content.length ? content.length : start + 100;
    const snippet = content.substring(start, end);
    const highlightedSnippet = snippet.replace(new RegExp(query, 'gi'), match => `<span class="highlight">${match}</span>`);
    return highlightedSnippet + '...';
  }
});
