import { TestBed } from '@angular/core/testing';

import { StationData } from './station-data';

describe('StationData', () => {
  let service: StationData;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(StationData);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
