import { useState } from 'react';
import { Icon } from './Icon';

export function InfoTooltip({ text, position = 'top' }) {
  const [isVisible, setIsVisible] = useState(false);

  const positionClasses = {
    top: 'bottom-full mb-2 left-1/2 -translate-x-1/2',
    right: 'left-full ml-2 top-1/2 -translate-y-1/2',
    bottom: 'top-full mt-2 left-1/2 -translate-x-1/2',
  };

  const arrowClasses = {
    top: 'top-full left-1/2 -translate-x-1/2 border-t-gray-600 border-l-transparent border-r-transparent border-b-transparent',
    right: 'right-full top-1/2 -translate-y-1/2 border-r-gray-600 border-t-transparent border-b-transparent border-l-transparent',
    bottom: 'bottom-full left-1/2 -translate-x-1/2 border-b-gray-600 border-l-transparent border-r-transparent border-t-transparent',
  };

  return (
    <div className="relative inline-block group">
      <button
        type="button"
        onClick={() => setIsVisible(!isVisible)}
        onMouseEnter={() => setIsVisible(true)}
        onMouseLeave={() => setIsVisible(false)}
        className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-gray-200 hover:bg-gray-300 text-gray-600 hover:text-gray-700 flex-shrink-0 ml-1"
        aria-label="Info"
      >
        <Icon name="info" size={12} />
      </button>

      {isVisible && (
        <div
          className={`absolute z-50 px-3 py-2 text-xs font-medium text-white bg-gray-600 rounded-lg shadow-lg whitespace-normal max-w-xs pointer-events-none ${positionClasses[position]}`}
          style={{ width: '200px' }}
        >
          {text}
          <div
            className={`absolute w-0 h-0 border-4 ${arrowClasses[position]}`}
          />
        </div>
      )}
    </div>
  );
}
